#!/usr/bin/env python3
"""Host online-ish probe + exponential reconnect + seatbelted self-repair (no models).

Composes with scripts/offline_improve.py (PR #148): reuses fleet_reachable,
peer_hosts, backoff_seconds. This layer does **not** load or bench models —
llama-bench stays in offline_improve only.

Usage:
  python3 scripts/reconnect_selfheal.py --probe-only
  python3 scripts/reconnect_selfheal.py --once
  python3 scripts/reconnect_selfheal.py --loop
  python3 scripts/reconnect_selfheal.py --once --repair          # apply seatbelted repairs
  python3 scripts/reconnect_selfheal.py --once --repair --dry-run  # default for repair

See docs/reconnect-selfheal.md. Issue #149.
"""
from __future__ import annotations

import argparse
import enum
import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# Import shared offline_improve helpers (same scripts/ on sys.path).
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import offline_improve as oi  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
import config_paths  # DUP-02/DUP-10 owner
STATE_ROOT = Path(
    os.environ.get("FAMILIA_RECONNECT_DIR")
    or (
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        / "familia"
        / "reconnect-selfheal"
    )
).expanduser()

# Documented backoff schedule (base=30, cap=900): fails 1..N → 30, 60, 120, 240, 480, 900…
BACKOFF_BASE_DEFAULT = 30.0
BACKOFF_CAP_DEFAULT = 900.0
BACKOFF_SCHEDULE_DOC = (30, 60, 120, 240, 480, 900)

DEFAULT_DNS_TARGET = os.environ.get("FAMILIA_RECONNECT_DNS", "1.1.1.1")
DEFAULT_SCREEN_NAME = os.environ.get("FAMILIA_SCREEN_NAME", "familia-server")


class ProbeState(str, enum.Enum):
    OFFLINE = "offline"
    LOCAL_OK_FLEET_DOWN = "local_ok_fleet_down"
    ONLINE_ISH = "online_ish"
    HEALTHY = "healthy"


class RepairAction(str, enum.Enum):
    """Explicit self-repair actions (seatbelted). See docs/reconnect-selfheal.md."""

    CHECK_SCREEN = "check_screen"
    RESTART_SCREEN_ATTACHED = "restart_screen_attached"
    REAPPLY_HOOK = "reapply_hook"
    GIT_FETCH_TIP = "git_fetch_tip"


@dataclass
class ProbeResult:
    state: str
    host: str
    when: str
    local_net: Dict[str, Any] = field(default_factory=dict)
    health: List[Dict[str, Any]] = field(default_factory=list)
    fleet: List[Dict[str, Any]] = field(default_factory=list)
    fleet_any_up: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _hostname() -> str:
    return (os.environ.get("FAMILIA_HOST") or socket.gethostname() or "unknown").split(".")[0].lower()


def detach_mode() -> str:
    """Effective DETACH_MODE (env FAMILIA_DETACH_MODE aliases DETACH_MODE)."""
    return (
        os.environ.get("FAMILIA_DETACH_MODE")
        or os.environ.get("DETACH_MODE")
        or "screen-attached"
    ).strip()


def screen_attached_ok(mode: Optional[str] = None) -> bool:
    return (mode or detach_mode()) == "screen-attached"


def backoff_seconds(fails: int, base: float = BACKOFF_BASE_DEFAULT, cap: float = BACKOFF_CAP_DEFAULT) -> float:
    """Reuse offline_improve schedule; documented in docs/reconnect-selfheal.md."""
    return oi.backoff_seconds(fails, base=base, cap=cap)


def backoff_with_jitter(
    fails: int,
    base: float = BACKOFF_BASE_DEFAULT,
    cap: float = BACKOFF_CAP_DEFAULT,
    *,
    jitter: float = 0.1,
    rng: Optional[random.Random] = None,
) -> float:
    """Exponential backoff with optional ±jitter fraction; still capped at `cap`."""
    raw = backoff_seconds(fails, base=base, cap=cap)
    if jitter <= 0:
        return raw
    r = rng or random
    # Uniform in [1-j, 1+j]; never exceed cap.
    factor = 1.0 + r.uniform(-jitter, jitter)
    return min(cap, max(0.0, raw * factor))


def documented_backoff_schedule(
    base: float = BACKOFF_BASE_DEFAULT,
    cap: float = BACKOFF_CAP_DEFAULT,
    n: int = 8,
) -> List[float]:
    return [backoff_seconds(i, base=base, cap=cap) for i in range(1, n + 1)]


# ---------------------------------------------------------------------------
# Probes (no models)
# ---------------------------------------------------------------------------

def probe_dns(
    target: str = DEFAULT_DNS_TARGET,
    *,
    timeout: float = 2.0,
    resolver: Optional[Callable[..., list]] = None,
) -> Dict[str, Any]:
    """Short DNS resolve of a public or peer name. Fail soft; never hang past timeout."""
    resolver = resolver or socket.getaddrinfo
    t0 = time.perf_counter()
    try:
        # Prefer AF_UNSPEC; limit wall time via alarm-less approach: getaddrinfo
        # itself may block — callers should keep timeout short and treat OSError.
        old = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(timeout)
            infos = resolver(target, None)
        finally:
            socket.setdefaulttimeout(old)
        ok = bool(infos)
        addrs = []
        for info in infos[:3]:
            try:
                addrs.append(info[4][0])
            except (IndexError, TypeError):
                pass
        return {
            "kind": "dns",
            "target": target,
            "ok": ok,
            "addrs": addrs,
            "sec": round(time.perf_counter() - t0, 4),
        }
    except (OSError, socket.timeout, TimeoutError) as e:
        return {
            "kind": "dns",
            "target": target,
            "ok": False,
            "error": str(e)[:160],
            "sec": round(time.perf_counter() - t0, 4),
        }


def probe_default_route(*, runner=None) -> Dict[str, Any]:
    """Best-effort default-route presence (Linux ip / FreeBSD route / POSIX). Fail soft."""
    runner = runner or subprocess.run
    # Linux
    try:
        p = runner(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if p.returncode == 0 and (p.stdout or "").strip():
            return {"kind": "default_route", "ok": True, "via": "ip", "line": (p.stdout or "").strip().splitlines()[0][:120]}
    except (OSError, subprocess.TimeoutExpired):
        pass
    # FreeBSD / generic
    try:
        p = runner(
            ["route", "-n", "get", "default"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        out = p.stdout or ""
        if p.returncode == 0 and ("gateway:" in out.lower() or "destination:" in out.lower()):
            return {"kind": "default_route", "ok": True, "via": "route", "line": out.strip().splitlines()[0][:120] if out.strip() else ""}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"kind": "default_route", "ok": False, "error": "no default route probe succeeded"}


def probe_local_health(
    urls: Sequence[str],
    *,
    timeout: float = 2.0,
    opener: Optional[Callable[..., Any]] = None,
) -> List[Dict[str, Any]]:
    """HTTP GET local /health URLs; fail soft per URL, never hang past timeout."""
    results = []
    for url in urls:
        entry: Dict[str, Any] = {"kind": "health", "url": url, "ok": False}
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(url, method="GET")
            if opener:
                resp = opener(req, timeout=timeout)
                code = getattr(resp, "status", None) or getattr(resp, "code", None) or 0
                entry["status"] = int(code)
                entry["ok"] = int(code) == 200
            else:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    entry["status"] = int(getattr(resp, "status", 200) or 200)
                    entry["ok"] = entry["status"] == 200
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as e:
            entry["error"] = str(e)[:160]
            if isinstance(e, urllib.error.HTTPError):
                entry["status"] = int(e.code)
        entry["sec"] = round(time.perf_counter() - t0, 4)
        results.append(entry)
    return results


def health_urls_from_env_and_graph(
    graph: dict,
    host: str,
    *,
    extra: Sequence[str] = (),
) -> List[str]:
    """Collect loopback health URLs from env + graph nodes bound on this host."""
    urls: List[str] = []
    env = os.environ.get("FAMILIA_RECONNECT_HEALTH_URLS", "").strip()
    if env:
        urls.extend(u.strip() for u in env.split(",") if u.strip())
    urls.extend(u for u in extra if u)
    # Graph: nodes with host==self and a port → http://127.0.0.1:PORT/health
    nodes = graph.get("nodes") or {}
    for _name, node in nodes.items():
        if not isinstance(node, dict):
            continue
        nh = (node.get("host") or "").lower()
        # Only nodes explicitly on this host (skip empty/other hosts to avoid probing foreign ports)
        if nh != host.lower():
            continue
        port = node.get("port")
        if not isinstance(port, int) or port < 1:
            continue
        # Skip SSH/system ports that are not llama health endpoints
        if port in (22, 8022, 6969):
            continue
        bind = (node.get("bind") or "127.0.0.1").strip()
        if bind in ("0.0.0.0", ""):
            bind = "127.0.0.1"
        elif bind not in ("127.0.0.1", "localhost", "::1"):
            # Non-loopback bind: still probe via 127.0.0.1 if it listens locally
            bind = "127.0.0.1"
        url = f"http://{bind}:{port}/health"
        if url not in urls:
            urls.append(url)
    # Cap to avoid long probe hangs on huge graphs
    return urls[:24]


def decide_state(
    *,
    local_net_ok: bool,
    fleet_any_up: bool,
    health_ok_any: bool,
    health_ok_all: bool,
    health_configured: bool,
) -> ProbeState:
    """Settle-once classifier for one probe cycle (no TOCTOU mid-cycle)."""
    if fleet_any_up:
        if not health_configured or health_ok_all:
            return ProbeState.HEALTHY
        # Fleet up but some local health missing → online-ish (path back, stack not green)
        return ProbeState.ONLINE_ISH
    if local_net_ok or health_ok_any:
        if health_ok_any and not fleet_any_up:
            return ProbeState.ONLINE_ISH
        return ProbeState.LOCAL_OK_FLEET_DOWN
    return ProbeState.OFFLINE


def run_probe(
    *,
    host: str,
    peers: Sequence[str],
    health_urls: Sequence[str],
    dns_target: str = DEFAULT_DNS_TARGET,
    timeout: float = 2.0,
    fleet_runner=None,
    route_runner=None,
    dns_resolver=None,
    health_opener=None,
    skip_fleet: bool = False,
) -> ProbeResult:
    """One settle-once online-ish probe. Zero model dependency."""
    notes: List[str] = []
    route = probe_default_route(runner=route_runner)
    dns = probe_dns(dns_target, timeout=timeout, resolver=dns_resolver)
    local_net_ok = bool(route.get("ok") or dns.get("ok"))
    if not local_net_ok:
        notes.append("local_net_down")

    health = probe_local_health(health_urls, timeout=timeout, opener=health_opener) if health_urls else []
    health_ok_any = any(h.get("ok") for h in health)
    health_ok_all = bool(health) and all(h.get("ok") for h in health)
    health_configured = bool(health_urls)

    fleet_rows: List[Dict[str, Any]] = []
    fleet_any_up = False
    if skip_fleet:
        notes.append("fleet_skipped")
    elif not peers:
        notes.append("no_peers")
    else:
        fleet_any_up, fleet_rows = oi.fleet_reachable(
            peers, timeout=max(1.0, timeout + 1.0), runner=fleet_runner
        )

    state = decide_state(
        local_net_ok=local_net_ok,
        fleet_any_up=fleet_any_up,
        health_ok_any=health_ok_any,
        health_ok_all=health_ok_all,
        health_configured=health_configured,
    )
    return ProbeResult(
        state=state.value,
        host=host,
        when=_now_iso(),
        local_net={"route": route, "dns": dns, "ok": local_net_ok},
        health=health,
        fleet=fleet_rows,
        fleet_any_up=fleet_any_up,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Self-repair (seatbelted)
# ---------------------------------------------------------------------------

@dataclass
class RepairResult:
    action: str
    ok: bool
    dry_run: bool
    detail: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def list_repair_actions() -> List[str]:
    return [a.value for a in RepairAction]


def check_screen_sessions(
    session: str = DEFAULT_SCREEN_NAME,
    *,
    runner=None,
) -> RepairResult:
    runner = runner or subprocess.run
    try:
        p = runner(["screen", "-ls"], capture_output=True, text=True, timeout=3)
        out = (p.stdout or "") + (p.stderr or "")
        present = session in out
        return RepairResult(
            action=RepairAction.CHECK_SCREEN.value,
            ok=True,
            dry_run=False,
            detail=f"session_present={present}",
            reason=out.strip()[:240] or f"rc={p.returncode}",
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return RepairResult(
            action=RepairAction.CHECK_SCREEN.value,
            ok=False,
            dry_run=False,
            detail="screen_ls_failed",
            reason=str(e)[:160],
        )


def repair_restart_screen_attached(
    *,
    dry_run: bool = True,
    mode: Optional[str] = None,
    runner=None,
    start_script: Optional[Path] = None,
) -> RepairResult:
    """Restart owned services only when DETACH_MODE=screen-attached.

    Never cold-Popen llama; never kill live servers outside this seatbelt.
    Default is dry-run / report-only.
    """
    mode = mode or detach_mode()
    if not screen_attached_ok(mode):
        return RepairResult(
            action=RepairAction.RESTART_SCREEN_ATTACHED.value,
            ok=False,
            dry_run=dry_run,
            detail="refused",
            reason=f"DETACH_MODE={mode!r} is not screen-attached; refusing llama/server restart",
        )
    start = start_script or (ROOT / "start.sh")
    cmd = ["env", f"DETACH_MODE=screen-attached", "sh", str(start), "--dry-run"] if dry_run else [
        "env", "DETACH_MODE=screen-attached", "sh", str(start),
    ]
    # Even when not dry_run, we still prefer start.sh's own dry path unless
    # FAMILIA_RECONNECT_ALLOW_START=1 — hard seatbelt against surprise live starts from automation.
    allow_live = os.environ.get("FAMILIA_RECONNECT_ALLOW_START") == "1"
    if not dry_run and not allow_live:
        return RepairResult(
            action=RepairAction.RESTART_SCREEN_ATTACHED.value,
            ok=False,
            dry_run=True,
            detail="seatbelt",
            reason="set FAMILIA_RECONNECT_ALLOW_START=1 to permit screen-attached start.sh (still no cold-Popen)",
        )
    if dry_run:
        return RepairResult(
            action=RepairAction.RESTART_SCREEN_ATTACHED.value,
            ok=True,
            dry_run=True,
            detail="would_run",
            reason=" ".join(cmd),
        )
    runner = runner or subprocess.run
    try:
        p = runner(cmd, capture_output=True, text=True, timeout=120)
        return RepairResult(
            action=RepairAction.RESTART_SCREEN_ATTACHED.value,
            ok=p.returncode == 0,
            dry_run=False,
            detail=f"rc={p.returncode}",
            reason=((p.stderr or "") + (p.stdout or ""))[-300:],
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return RepairResult(
            action=RepairAction.RESTART_SCREEN_ATTACHED.value,
            ok=False,
            dry_run=False,
            detail="exec_failed",
            reason=str(e)[:160],
        )


def repair_reapply_hook(
    *,
    dry_run: bool = True,
    hook: Optional[str] = None,
    runner=None,
) -> RepairResult:
    """Run FAMILIA_RECONNECT_HOOK (script-only nexus/SSH/tunnel rejoin). Stub if unset."""
    hook = hook if hook is not None else os.environ.get("FAMILIA_RECONNECT_HOOK", "").strip()
    if not hook:
        return RepairResult(
            action=RepairAction.REAPPLY_HOOK.value,
            ok=True,
            dry_run=dry_run,
            detail="noop",
            reason="FAMILIA_RECONNECT_HOOK unset; stub — set to a script for nexus/SSH/tunnel rejoin",
        )
    if dry_run:
        return RepairResult(
            action=RepairAction.REAPPLY_HOOK.value,
            ok=True,
            dry_run=True,
            detail="would_run",
            reason=hook,
        )
    runner = runner or subprocess.run
    try:
        p = runner(["sh", "-c", hook], capture_output=True, text=True, timeout=60)
        return RepairResult(
            action=RepairAction.REAPPLY_HOOK.value,
            ok=p.returncode == 0,
            dry_run=False,
            detail=f"rc={p.returncode}",
            reason=((p.stderr or "") + (p.stdout or ""))[-300:],
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return RepairResult(
            action=RepairAction.REAPPLY_HOOK.value,
            ok=False,
            dry_run=False,
            detail="exec_failed",
            reason=str(e)[:160],
        )


def _git_tree_clean(repo: Path, *, runner=None) -> Tuple[bool, str]:
    runner = runner or subprocess.run
    try:
        p = runner(
            ["git", "-C", str(repo), "status", "--porcelain", "--ignore-submodules=all"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if p.returncode != 0:
            return False, (p.stderr or "git status failed")[:160]
        dirty = bool((p.stdout or "").strip())
        return (not dirty), ("dirty" if dirty else "clean")
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)[:160]


def repair_git_fetch_tip(
    *,
    dry_run: bool = True,
    repo: Optional[Path] = None,
    runner=None,
) -> RepairResult:
    """Optional git fetch tip when FAMILIA_RECONNECT_PULL=1. Fetch only: local edits are never touched or blocking."""
    if os.environ.get("FAMILIA_RECONNECT_PULL") != "1":
        return RepairResult(
            action=RepairAction.GIT_FETCH_TIP.value,
            ok=True,
            dry_run=dry_run,
            detail="skipped",
            reason="FAMILIA_RECONNECT_PULL!=1",
        )
    repo = repo or ROOT
    # git fetch never touches the working tree, so local edits never block it (familia #181 U10).
    clean, why = _git_tree_clean(repo, runner=runner)
    cmd = ["git", "-C", str(repo), "fetch", "--all", "--prune"]
    if dry_run:
        return RepairResult(
            action=RepairAction.GIT_FETCH_TIP.value,
            ok=True,
            dry_run=True,
            detail="would_run",
            reason=" ".join(cmd),
        )
    runner = runner or subprocess.run
    try:
        p = runner(cmd, capture_output=True, text=True, timeout=120)
        return RepairResult(
            action=RepairAction.GIT_FETCH_TIP.value,
            ok=p.returncode == 0,
            dry_run=False,
            detail=f"rc={p.returncode}",
            reason=((p.stderr or "") + (p.stdout or ""))[-300:],
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return RepairResult(
            action=RepairAction.GIT_FETCH_TIP.value,
            ok=False,
            dry_run=False,
            detail="exec_failed",
            reason=str(e)[:160],
        )


def run_self_repair(
    *,
    dry_run: bool = True,
    do_restart: bool = True,
    do_hook: bool = True,
    do_git: bool = True,
    runner=None,
) -> List[RepairResult]:
    """Bounded self-repair sequence. Default dry-run; restart seatbelted."""
    out: List[RepairResult] = []
    out.append(check_screen_sessions(runner=runner))
    if do_restart:
        out.append(repair_restart_screen_attached(dry_run=dry_run, runner=runner))
    if do_hook:
        out.append(repair_reapply_hook(dry_run=dry_run, runner=runner))
    if do_git:
        out.append(repair_git_fetch_tip(dry_run=dry_run, runner=runner))
    return out


def persist_probe(result: ProbeResult, state_dir: Path = STATE_ROOT) -> Path:
    host = result.host or _hostname()
    d = state_dir / host
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"probe-{stamp}.json"
    payload = result.to_dict()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (d / "latest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (d / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "when": result.when,
            "host": host,
            "state": result.state,
            "fleet_any_up": result.fleet_any_up,
            "file": str(path),
        }) + "\n")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="reconnect_selfheal",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--probe-only", action="store_true", help="run one probe, print JSON, exit 0/1/2 by state")
    mode.add_argument("--once", action="store_true", help="probe (+ optional repair) once, then exit")
    mode.add_argument("--loop", action="store_true", help="probe → optional repair → backoff → retry until healthy/online_ish")
    ap.add_argument("--repair", action="store_true", help="enable self-repair actions (still dry-run unless --no-dry-run)")
    ap.add_argument("--dry-run", action="store_true", default=False, help="force dry-run for repair (default when --repair)")
    ap.add_argument("--no-dry-run", action="store_true", help="allow non-dry repair (still seatbelted; needs FAMILIA_RECONNECT_ALLOW_START=1 for restarts)")
    ap.add_argument("--host", default=_hostname())
    ap.add_argument("--graph", default=None)  # DUP-02: resolved lazily after parse
    ap.add_argument("--peers", default="", help="comma-separated peer SSH aliases")
    ap.add_argument("--health-urls", default="", help="comma-separated local health URLs (else graph/env)")
    ap.add_argument("--dns", default=DEFAULT_DNS_TARGET)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--base-sleep", type=float, default=float(os.environ.get("FAMILIA_RECONNECT_BASE", BACKOFF_BASE_DEFAULT)))
    ap.add_argument("--cap-sleep", type=float, default=float(os.environ.get("FAMILIA_RECONNECT_CAP", BACKOFF_CAP_DEFAULT)))
    ap.add_argument("--jitter", type=float, default=float(os.environ.get("FAMILIA_RECONNECT_JITTER", "0.1")))
    ap.add_argument("--max-attempts", type=int, default=0, help="with --loop: stop after N attempts (0=unlimited)")
    ap.add_argument("--stop-at", default="online_ish", choices=["online_ish", "healthy"],
                    help="loop success threshold (default: online_ish)")
    ap.add_argument("--state-dir", default=str(STATE_ROOT))
    ap.add_argument("--list-actions", action="store_true", help="print self-repair action enum and exit 0")
    ap.add_argument("--show-backoff", action="store_true", help="print documented backoff schedule and exit 0")
    args = ap.parse_args(list(argv) if argv is not None else None)
    args.graph = config_paths.graph_path(args.graph)  # DUP-02 lazy resolve

    if args.list_actions:
        print(json.dumps({"repair_actions": list_repair_actions(), "detach_mode": detach_mode()}, indent=2))
        return 0
    if args.show_backoff:
        sched = documented_backoff_schedule(args.base_sleep, args.cap_sleep)
        print(json.dumps({
            "base": args.base_sleep,
            "cap": args.cap_sleep,
            "schedule_seconds": sched,
            "doc_tuple": list(BACKOFF_SCHEDULE_DOC),
            "formula": "min(cap, base * 2**(fails-1))",
        }, indent=2))
        return 0

    state_dir = Path(args.state_dir).expanduser()
    graph = oi._load_graph(Path(args.graph))
    peers = [p.strip() for p in args.peers.split(",") if p.strip()] or oi.peer_hosts(graph, args.host)
    if not peers:
        peers = [p for p in ("miryam", "box", "qodesh", "angel") if p.lower() != args.host.lower()]

    extra_health = [u.strip() for u in args.health_urls.split(",") if u.strip()]
    health_urls = health_urls_from_env_and_graph(graph, args.host, extra=extra_health)

    dry_repair = True
    if args.repair:
        dry_repair = not args.no_dry_run
        if args.dry_run:
            dry_repair = True

    if not args.probe_only and not args.once and not args.loop:
        args.probe_only = True

    success_states = {ProbeState.HEALTHY.value}
    if args.stop_at == "online_ish":
        success_states.add(ProbeState.ONLINE_ISH.value)

    attempts = 0
    fails = 0
    while True:
        attempts += 1
        # Settle-once: one probe result drives this iteration's decisions.
        probe = run_probe(
            host=args.host,
            peers=peers,
            health_urls=health_urls,
            dns_target=args.dns,
            timeout=args.timeout,
        )
        path = persist_probe(probe, state_dir)
        event: Dict[str, Any] = {
            "event": "probe",
            "attempt": attempts,
            "persisted": str(path),
            "probe": probe.to_dict(),
        }

        repairs: List[dict] = []
        if args.repair and probe.state not in success_states:
            # Only self-repair when not yet at success threshold.
            for r in run_self_repair(dry_run=dry_repair):
                repairs.append(r.to_dict())
            event["repairs"] = repairs

        print(json.dumps(event, indent=2))

        if args.probe_only:
            if probe.state == ProbeState.HEALTHY.value:
                return 0
            if probe.state == ProbeState.ONLINE_ISH.value:
                return 0
            if probe.state == ProbeState.LOCAL_OK_FLEET_DOWN.value:
                return 2
            return 1

        if probe.state in success_states:
            print(
                f"reconnect_selfheal: {probe.state} from {args.host}; path back ok",
                file=sys.stderr,
            )
            return 0

        fails += 1
        if args.once or (args.max_attempts and attempts >= args.max_attempts):
            sleep_s = backoff_with_jitter(fails, args.base_sleep, args.cap_sleep, jitter=args.jitter)
            print(
                f"reconnect_selfheal: state={probe.state}; suggested sleep {sleep_s:.1f}s "
                f"(use --loop to auto-retry)",
                file=sys.stderr,
            )
            return 2 if probe.state != ProbeState.OFFLINE.value else 1

        sleep_s = backoff_with_jitter(fails, args.base_sleep, args.cap_sleep, jitter=args.jitter)
        print(
            f"reconnect_selfheal: state={probe.state}; sleeping {sleep_s:.1f}s before retry",
            file=sys.stderr,
        )
        time.sleep(sleep_s)


if __name__ == "__main__":
    sys.exit(main())
