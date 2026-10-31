#!/usr/bin/env python3
"""Offline performance-improvement loop for a disconnected familia host.

When a host loses fleet connectivity it should stay useful: run a bounded local
perf cycle, persist results, back off, and retry reconnect. When peers are
reachable again, print a short summary of what improved offline and exit so
normal duty (start.sh / monitor / with-fleet) can resume.

This is the on-host half of "going offline means they can still be useful."
Fleet-wide nudging (Researcher weekday check) is separate.

Usage:
  python3 scripts/offline_improve.py --check-only
  python3 scripts/offline_improve.py --once
  python3 scripts/offline_improve.py --loop
  python3 scripts/offline_improve.py --offline --once   # force improve cycle
  FAMILIA_OFFLINE_IMPROVE=1 python3 scripts/offline_improve.py --loop

See docs/offline-improve.md. Continuity gum: leave a setup.goals hook later;
do not add Continuity-owned menu rows here.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
import config_paths  # DUP-02/DUP-10 owner
STATE_ROOT = Path(
    os.environ.get("FAMILIA_OFFLINE_IMPROVE_DIR")
    or (Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "familia" / "offline-improve")
).expanduser()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _hostname() -> str:
    return (os.environ.get("FAMILIA_HOST") or socket.gethostname() or "unknown").split(".")[0].lower()


def _load_graph(path: Path) -> dict:
    try:
        import yaml
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def peer_hosts(graph: dict, self_name: str) -> List[str]:
    """Other declared hosts (exclude self). Prefer measured/desktop peers for SSH checks."""
    hosts = graph.get("hosts") or {}
    out = []
    for name in hosts:
        if name.lower() == self_name.lower():
            continue
        out.append(name)
    return out


def fleet_reachable(
    peers: Sequence[str],
    *,
    timeout: float = 3.0,
    ssh_bin: str = "ssh",
    runner=None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Return (any_peer_up, per-peer results). Uses ssh BatchMode; no passwords."""
    runner = runner or subprocess.run
    results = []
    any_up = False
    for peer in peers:
        cmd = [
            ssh_bin, "-T", "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={max(1, int(timeout))}",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "LogLevel=ERROR",
            peer, "echo familia-fleet-ok",
        ]
        try:
            p = runner(cmd, capture_output=True, text=True, timeout=timeout + 2)
            ok = p.returncode == 0 and "familia-fleet-ok" in (p.stdout or "")
        except (OSError, subprocess.TimeoutExpired) as e:
            ok = False
            p = type("R", (), {"returncode": -1, "stderr": str(e), "stdout": ""})()
        results.append({
            "peer": peer,
            "ok": ok,
            "rc": getattr(p, "returncode", -1),
            "err": ((p.stderr or "") if not ok else "")[:120],
        })
        if ok:
            any_up = True
    return any_up, results


def _threads() -> int:
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def _mem_mib() -> Optional[int]:
    if sys.platform.startswith("linux"):
        try:
            for line in open("/proc/meminfo", encoding="utf-8"):
                if line.startswith("MemAvailable:") or line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform.startswith("freebsd"):
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.physmem"], text=True).strip()
            return int(out) // 1048576
        except (OSError, subprocess.CalledProcessError, ValueError):
            return None
    return None


def _find_small_gguf() -> Optional[Path]:
    """Prefer a tiny local GGUF for bounded benches; never Nanbeige-class by default."""
    env = os.environ.get("FAMILIA_OFFLINE_IMPROVE_GGUF")
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() else None
    candidates = [
        Path.home() / ".local/share/gguf/models/general/LFM2.5-1.2B-Instruct-Q4_K_M.gguf",
        Path.home() / ".local/share/gguf/models/general/SmolLM2-135M-Instruct-Q4_0.gguf",
        Path.home() / ".local/share/gguf/models/general/smollm2-135m-instruct-q4_0.gguf",
        ROOT / "models",
    ]
    for c in candidates:
        if c.is_file():
            return c
        if c.is_dir():
            for pat in ("*SmolLM*", "*smollm*", "*LFM2.5-1.2B*", "*135M*", "*0.5B*"):
                hits = sorted(c.rglob(pat + "*.gguf"))
                if hits:
                    return hits[0]
    return None


def _find_llama_bench() -> Optional[str]:
    env = os.environ.get("LLAMA_BENCH") or os.environ.get("LLAMA_BENCH_BIN")
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return env
    which = subprocess.run(["sh", "-c", "command -v llama-bench"], capture_output=True, text=True)
    if which.returncode == 0 and which.stdout.strip():
        return which.stdout.strip()
    for rel in (
        "code-bootstraps-llama.cpp/build-linux-x86_64/bin/llama-bench",
        "code-bootstraps-llama.cpp/build-freebsd/bin/llama-bench",
        "code-bootstraps-llama.cpp/build/bin/llama-bench",
    ):
        p = ROOT / rel
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def run_host_ram_probe(mib: int = 32) -> Dict[str, Any]:
    """Stdlib memcpy probe (same idea as probe_links.host_ram)."""
    src = bytearray(os.urandom(1 << 20)) * max(1, mib)
    dst = bytearray(len(src))
    dst[:] = src
    reps = 4
    t0 = time.perf_counter()
    for _ in range(reps):
        dst[:] = src
    sec = time.perf_counter() - t0
    return {
        "kind": "host_ram",
        "bytes": len(src),
        "reps": reps,
        "sec": round(sec, 6),
        "GBps": round(len(src) * reps / sec / 1e9, 3) if sec else None,
    }


def run_llama_bench_bounded(
    bench: str,
    gguf: Path,
    threads: Sequence[int],
    *,
    prompt: int = 128,
    n_gen: int = 32,
    reps: int = 1,
    timeout: float = 180.0,
    runner=None,
) -> Dict[str, Any]:
    """One bounded llama-bench sweep; FreeBSD/Linux friendly (no systemd-run)."""
    runner = runner or subprocess.run
    t_list = ",".join(str(t) for t in threads)
    cmd = [
        bench, "-m", str(gguf), "-o", "jsonl",
        "-t", t_list, "-p", str(prompt), "-n", str(n_gen), "-r", str(reps),
    ]
    # Prefer mmap when available; ignore unknown flags by not passing load-mode aliases.
    try:
        p = runner(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"kind": "llama-bench", "ok": False, "error": "timeout", "cmd": cmd}
    except OSError as e:
        return {"kind": "llama-bench", "ok": False, "error": str(e), "cmd": cmd}
    rows = []
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    best = None
    for row in rows:
        ts = row.get("avg_ts")
        if isinstance(ts, (int, float)) and (best is None or ts > best.get("avg_ts", 0)):
            best = row
    return {
        "kind": "llama-bench",
        "ok": p.returncode == 0 and bool(rows),
        "rc": p.returncode,
        "gguf": str(gguf),
        "threads_tried": list(threads),
        "n_rows": len(rows),
        "best_avg_ts": best.get("avg_ts") if best else None,
        "best": {k: best.get(k) for k in ("n_threads", "n_prompt", "n_gen", "avg_ts", "type_k")} if best else None,
        "stderr_tail": ((p.stderr or "") + (p.stdout or ""))[-400:] if p.returncode else "",
    }


def improve_cycle(
    *,
    host: str,
    allow_bench: bool = True,
    runner=None,
) -> Dict[str, Any]:
    """Run one bounded local improve cycle and return a result dict."""
    ncpu = _threads()
    thread_grid = sorted({1, max(1, ncpu // 2), ncpu})
    result: Dict[str, Any] = {
        "host": host,
        "when": _now_iso(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "threads_host": ncpu,
        "mem_mib": _mem_mib(),
        "steps": [],
    }
    result["steps"].append(run_host_ram_probe())
    if allow_bench:
        bench = _find_llama_bench()
        gguf = _find_small_gguf()
        if not bench:
            result["steps"].append({"kind": "llama-bench", "ok": False, "skipped": "no llama-bench"})
        elif not gguf:
            result["steps"].append({"kind": "llama-bench", "ok": False, "skipped": "no small GGUF"})
        else:
            result["steps"].append(
                run_llama_bench_bounded(bench, gguf, thread_grid, runner=runner)
            )
    return result


def persist(result: Dict[str, Any], state_dir: Path = STATE_ROOT) -> Path:
    host = result.get("host") or _hostname()
    d = state_dir / host
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"improve-{stamp}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    latest = d / "latest.json"
    latest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    # append summary line
    summary = d / "history.jsonl"
    with summary.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "when": result.get("when"),
            "host": host,
            "best_avg_ts": next(
                (s.get("best_avg_ts") for s in result.get("steps", []) if s.get("kind") == "llama-bench"),
                None,
            ),
            "host_ram_GBps": next(
                (s.get("GBps") for s in result.get("steps", []) if s.get("kind") == "host_ram"),
                None,
            ),
            "file": str(path),
        }) + "\n")
    return path


def load_pending_summary(host: str, state_dir: Path = STATE_ROOT) -> Optional[dict]:
    latest = state_dir / host / "latest.json"
    if not latest.is_file():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def backoff_seconds(fails: int, base: float = 30.0, cap: float = 900.0) -> float:
    """Exponential backoff between reconnect attempts (seconds)."""
    return min(cap, base * (2 ** max(0, fails - 1)))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="offline_improve",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true", help="print fleet reachability and exit 0/1")
    mode.add_argument("--once", action="store_true", help="one improve cycle if offline (or with --offline), then exit")
    mode.add_argument("--loop", action="store_true", help="improve → sleep/backoff → reconnect check → repeat until online")
    ap.add_argument("--offline", action="store_true", help="force offline mode (skip fleet check / treat as disconnected)")
    ap.add_argument("--host", default=_hostname(), help="graph host name for this machine (default: hostname)")
    ap.add_argument("--graph", default=config_paths.graph_path())
    ap.add_argument("--peers", default="", help="comma-separated peer host aliases (default: other graph hosts)")
    ap.add_argument("--no-bench", action="store_true", help="skip llama-bench; host_ram probe only")
    ap.add_argument("--base-sleep", type=float, default=float(os.environ.get("FAMILIA_OFFLINE_IMPROVE_BASE", 30)))
    ap.add_argument("--cap-sleep", type=float, default=float(os.environ.get("FAMILIA_OFFLINE_IMPROVE_CAP", 900)))
    ap.add_argument("--max-cycles", type=int, default=0, help="with --loop: stop after N improve cycles (0=unlimited)")
    ap.add_argument("--state-dir", default=str(STATE_ROOT))
    args = ap.parse_args(list(argv) if argv is not None else None)

    state_dir = Path(args.state_dir).expanduser()
    graph = _load_graph(Path(args.graph))
    peers = [p.strip() for p in args.peers.split(",") if p.strip()] or peer_hosts(graph, args.host)
    # Always try common fleet aliases if graph empty
    if not peers:
        peers = [p for p in ("miryam", "box", "qodesh", "angel") if p.lower() != args.host.lower()]

    def check() -> Tuple[bool, List[dict]]:
        if args.offline or os.environ.get("FAMILIA_OFFLINE_IMPROVE") == "force":
            return False, [{"peer": "*", "ok": False, "rc": 0, "err": "forced --offline"}]
        if not peers:
            return False, [{"peer": "*", "ok": False, "rc": 0, "err": "no peers configured"}]
        return fleet_reachable(peers)

    if args.check_only:
        up, rows = check()
        print(json.dumps({"host": args.host, "online": up, "peers": rows}, indent=2))
        return 0 if up else 1

    if not args.once and not args.loop:
        # default: check; if offline run once, if online report pending
        args.once = True

    cycles = 0
    fails = 0
    while True:
        up, rows = check()
        if up:
            pending = load_pending_summary(args.host, state_dir)
            print(f"offline_improve: fleet reachable from {args.host}; resuming normal duty", file=sys.stderr)
            for r in rows:
                if r.get("ok"):
                    print(f"  peer {r['peer']}: up", file=sys.stderr)
            if pending:
                print(json.dumps({
                    "event": "back_online",
                    "host": args.host,
                    "offline_improve_latest": {
                        "when": pending.get("when"),
                        "best_avg_ts": next(
                            (s.get("best_avg_ts") for s in pending.get("steps", []) if s.get("kind") == "llama-bench"),
                            None,
                        ),
                        "host_ram_GBps": next(
                            (s.get("GBps") for s in pending.get("steps", []) if s.get("kind") == "host_ram"),
                            None,
                        ),
                    },
                }, indent=2))
            return 0

        print(f"offline_improve: fleet unreachable from {args.host}; starting improve cycle", file=sys.stderr)
        for r in rows:
            print(f"  peer {r['peer']}: down ({(r.get('err') or 'no route')[:80]})", file=sys.stderr)

        result = improve_cycle(host=args.host, allow_bench=not args.no_bench)
        path = persist(result, state_dir)
        cycles += 1
        fails += 1
        print(json.dumps({
            "event": "improve_cycle",
            "host": args.host,
            "cycle": cycles,
            "persisted": str(path),
            "best_avg_ts": next(
                (s.get("best_avg_ts") for s in result.get("steps", []) if s.get("kind") == "llama-bench"),
                None,
            ),
            "host_ram_GBps": next(
                (s.get("GBps") for s in result.get("steps", []) if s.get("kind") == "host_ram"),
                None,
            ),
        }, indent=2))

        if args.once or (args.max_cycles and cycles >= args.max_cycles):
            sleep_s = backoff_seconds(fails, args.base_sleep, args.cap_sleep)
            print(
                f"offline_improve: cycle done; retry fleet later "
                f"(suggested sleep {int(sleep_s)}s; use --loop to auto-retry)",
                file=sys.stderr,
            )
            return 2  # offline after improve

        sleep_s = backoff_seconds(fails, args.base_sleep, args.cap_sleep)
        print(f"offline_improve: sleeping {int(sleep_s)}s before reconnect check", file=sys.stderr)
        time.sleep(sleep_s)


if __name__ == "__main__":
    sys.exit(main())
