#!/usr/bin/env python3
"""Android/Termux offline fallback: queue commands locally, post to a GitHub
issue when SSH/Wi-Fi to the fleet returns, then pull later comments back.

Issue #332. Default target issue is #332; override with --issue N or
FAMILIA_OFFLINE_ISSUE (positive integer). New standalone module — does not
edit familia_home / proto_chat / open_ui / ui_bridge / menus / graph.yaml /
FreeBSD or Termux docs. Wire-in suggestions belong in the PR body, not in
those files. Sync/enqueue/flush/pull are operator-run only: do not auto-queue
from proto_chat.sh or other launchers.

State lives under $XDG_STATE_HOME/familia/offline (fallback
$HOME/.local/state/familia/offline). Dirs 0700, files 0600, symlink-refusing,
flock-serialized. Each run gets exactly one private mkdtemp under that state
dir (never /tmp).

Connectivity: short TCP connect to FAMILIA_OFFLINE_SSH_HOST:FAMILIA_OFFLINE_SSH_PORT
(env/config only; no hostnames in tracked files), plus optional
termux-wifi-connectioninfo when present. Exponential backoff between probes.

GitHub: gh CLI when available, else REST with GITHUB_TOKEN/GH_TOKEN. Tokens
are never logged. Tests must mock the network; this module posts nothing unless
flush/sync is invoked with a live token (tests inject a fake poster).

A later issue comment counts as a reply only when it quotes our marker
(familia-offline-queue:id=<uuid> or the bare entry id) AND the author is
trusted (author_association OWNER/MEMBER/COLLABORATOR, or a login listed in
FAMILIA_OFFLINE_REPLY_ALLOWLIST). Other later comments are ignored. Outgoing
posts and stored reply bodies are scrubbed of IPs, ports, emails, tokens and
private-looking hostnames; control/escape characters are stripped.

See docs/offline-queue.md.

Usage:
  python3 scripts/offline_queue.py probe
  python3 scripts/offline_queue.py enqueue -- "status please"   # defaults to #332
  python3 scripts/offline_queue.py enqueue --issue 332 -- "status please"
  python3 scripts/offline_queue.py status
  python3 scripts/offline_queue.py flush
  python3 scripts/offline_queue.py pull
  python3 scripts/offline_queue.py sync   # operator-run only
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import runtime_dir as rd  # noqa: E402

APP = "familia"
STATE_LEAF = "offline"
MARKER_RE = re.compile(
    r"<!--\s*familia-offline-queue:id=([0-9a-fA-F-]{36})\s*-->"
)
DEFAULT_REPO = os.environ.get("FAMILIA_OFFLINE_REPO", "brianreborn/familia")
DEFAULT_ISSUE = 332
DEFAULT_SSH_PORT = 22
PROBE_TIMEOUT_DEFAULT = 2.0
BACKOFF_BASE = 5.0
BACKOFF_CAP = 300.0


class OfflineQueueError(RuntimeError):
    pass


def parse_positive_issue(value) -> int:
    """Validate a positive integer issue number (CLI, env, or default)."""
    if isinstance(value, bool):
        raise OfflineQueueError("issue number must be a positive integer")
    if isinstance(value, int):
        n = value
    else:
        s = str(value).strip()
        if not s or not s.isdigit():
            raise OfflineQueueError("issue number must be a positive integer, got %r" % (value,))
        n = int(s)
    if n < 1:
        raise OfflineQueueError("issue number must be >= 1, got %d" % n)
    return n


def resolve_issue_number(cli_value=None, environ=None) -> int:
    """Resolve issue: --issue N, else FAMILIA_OFFLINE_ISSUE, else DEFAULT_ISSUE (#332)."""
    env = os.environ if environ is None else environ
    if cli_value is not None:
        return parse_positive_issue(cli_value)
    raw = env.get("FAMILIA_OFFLINE_ISSUE")
    if raw is not None and str(raw).strip() != "":
        return parse_positive_issue(raw)
    return parse_positive_issue(DEFAULT_ISSUE)


def positive_issue_arg(value: str) -> int:
    """argparse type: positive int issue number."""
    try:
        return parse_positive_issue(value)
    except OfflineQueueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


# ---------------------------------------------------------------- time / ids


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- state dir (0700, no symlink, flock)


def state_dir(environ: Optional[dict] = None) -> Path:
    """$XDG_STATE_HOME/familia/offline or $HOME/.local/state/familia/offline.

    Override with FAMILIA_OFFLINE_DIR. Always private (0700, our uid, not a symlink).
    """
    env = os.environ if environ is None else environ
    override = (env.get("FAMILIA_OFFLINE_DIR") or "").strip()
    if override:
        path = Path(override).expanduser()
    else:
        xdg = (env.get("XDG_STATE_HOME") or "").strip()
        if not xdg:
            home = env.get("HOME") or str(Path.home())
            xdg = str(Path(home) / ".local" / "state")
        path = Path(xdg) / APP / STATE_LEAF
    return Path(_ensure_state_tree(str(path)))


def _ensure_state_tree(path: str) -> str:
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        old = os.umask(0o077)
        try:
            os.makedirs(parent, 0o700, exist_ok=True)
        finally:
            os.umask(old)
    old = os.umask(0o077)
    try:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
    finally:
        os.umask(old)
    return rd.check_private_dir(path)


def _run_workdir(state: Path) -> Path:
    """Exactly one private mkdtemp under *state* for this process run. Never /tmp."""
    rd.check_private_dir(str(state))
    work = tempfile.mkdtemp(prefix=".run-", dir=str(state))
    try:
        st = os.lstat(work)
        if stat.S_ISLNK(st.st_mode) or (st.st_mode & 0o077):
            raise OfflineQueueError("run workdir is not private: %s" % work)
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise OfflineQueueError("run workdir foreign owner: %s" % work)
    except OSError as e:
        shutil.rmtree(work, ignore_errors=True)
        raise OfflineQueueError("run workdir check failed: %s" % e) from e
    return Path(work)


class RunContext:
    """Owns the single mkdtemp for a CLI invocation; cleans up on exit."""

    def __init__(self, state: Optional[Path] = None, environ: Optional[dict] = None):
        self.state = state or state_dir(environ)
        self.work: Optional[Path] = None
        self._lock_fd: Optional[int] = None

    def __enter__(self) -> "RunContext":
        self.work = _run_workdir(self.state)
        lock_path = str(self.state / "offline.lock")
        self._lock_fd = rd.open_lock(lock_path)
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None
        if self.work is not None:
            shutil.rmtree(str(self.work), ignore_errors=True)
            self.work = None


def _write_private(path: Path, data: bytes) -> None:
    rd.check_private_dir(str(path.parent))
    fd = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _atomic_write_json(path: Path, obj: Any, work: Path) -> None:
    tmp = work / (path.name + ".tmp")
    payload = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_private(tmp, payload)
    os.replace(str(tmp), str(path))
    try:
        os.chmod(str(path), 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------- queue records


def queue_dir(state: Path) -> Path:
    d = state / "queue"
    old = os.umask(0o077)
    try:
        os.makedirs(str(d), 0o700, exist_ok=True)
    finally:
        os.umask(old)
    return Path(rd.check_private_dir(str(d)))


def responses_dir(state: Path) -> Path:
    d = state / "responses"
    old = os.umask(0o077)
    try:
        os.makedirs(str(d), 0o700, exist_ok=True)
    finally:
        os.umask(old)
    return Path(rd.check_private_dir(str(d)))


def _entry_path(state: Path, entry_id: str) -> Path:
    safe = re.sub(r"[^0-9a-fA-F-]", "", entry_id)
    if safe != entry_id or len(entry_id) < 32:
        raise OfflineQueueError("invalid entry id")
    return queue_dir(state) / ("%s.json" % entry_id)


def load_entry(state: Path, entry_id: str) -> dict:
    path = _entry_path(state, entry_id)
    try:
        st = os.lstat(path)
    except FileNotFoundError as e:
        raise OfflineQueueError("no such entry: %s" % entry_id) from e
    if stat.S_ISLNK(st.st_mode):
        raise OfflineQueueError("refusing symlink entry: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_entries(state: Path) -> List[dict]:
    d = queue_dir(state)
    out: List[dict] = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        path = d / name
        try:
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                continue
            with open(path, "r", encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    out.sort(key=lambda e: e.get("created_at") or "")
    return out


def enqueue(
    body: str,
    *,
    issue: int,
    repo: str = DEFAULT_REPO,
    state: Optional[Path] = None,
    work: Optional[Path] = None,
    entry_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> dict:
    """Append a queued command. Returns the entry dict."""
    body = (body or "").strip("\n")
    if not body.strip():
        raise OfflineQueueError("empty command body")
    if issue < 1:
        raise OfflineQueueError("issue number must be >= 1")
    if "/" not in repo or repo.count("/") != 1:
        raise OfflineQueueError("repo must be owner/name")
    st = state or state_dir()
    eid = entry_id or _new_id()
    entry = {
        "id": eid,
        "issue": int(issue),
        "repo": repo,
        "body": body,
        "created_at": created_at or _now_iso(),
        "status": "queued",
        "comment_id": None,
        "posted_at": None,
        "response_comment_ids": [],
        "last_error": None,
    }
    path = _entry_path(st, eid)
    if work is None:
        # caller outside RunContext: still write privately via temp under state
        with RunContext(st) as ctx:
            _atomic_write_json(path, entry, ctx.work)  # type: ignore[arg-type]
    else:
        _atomic_write_json(path, entry, work)
    return entry


def save_entry(state: Path, entry: dict, work: Path) -> None:
    path = _entry_path(state, entry["id"])
    _atomic_write_json(path, entry, work)


# ---------------------------------------------------------------- connectivity


def backoff_seconds(fails: int, base: float = BACKOFF_BASE, cap: float = BACKOFF_CAP) -> float:
    if fails < 1:
        return 0.0
    return float(min(cap, base * (2 ** (fails - 1))))


def ssh_probe_target(environ: Optional[dict] = None) -> Tuple[str, int]:
    """Host/port from env only. Placeholders refused; no defaults with real hosts."""
    env = os.environ if environ is None else environ
    host = (env.get("FAMILIA_OFFLINE_SSH_HOST") or env.get("FAMILIA_SSH_HOST") or "").strip()
    port_s = (env.get("FAMILIA_OFFLINE_SSH_PORT") or env.get("FAMILIA_SSH_PORT") or str(DEFAULT_SSH_PORT)).strip()
    if not host:
        raise OfflineQueueError(
            "set FAMILIA_OFFLINE_SSH_HOST (or FAMILIA_SSH_HOST) to the fleet SSH host; "
            "no hostname is stored in the repo"
        )
    # Refuse obvious placeholders so misconfig fails closed in prod.
    if host.startswith("${") or host in ("HOST", "hostname", "example.invalid", "CHANGE_ME"):
        raise OfflineQueueError("FAMILIA_OFFLINE_SSH_HOST looks like a placeholder: configure a real host via env")
    try:
        port = int(port_s)
    except ValueError as e:
        raise OfflineQueueError("invalid SSH port: %r" % port_s) from e
    if not (1 <= port <= 65535):
        raise OfflineQueueError("SSH port out of range: %d" % port)
    return host, port


def tcp_reachable(
    host: str,
    port: int,
    *,
    timeout: float = PROBE_TIMEOUT_DEFAULT,
    connector: Optional[Callable[..., None]] = None,
) -> Tuple[bool, str]:
    """Cheap TCP connect. *connector* is injectable for tests (raises on failure)."""
    connect = connector or socket.create_connection
    try:
        sock = connect((host, port), timeout)
        try:
            if hasattr(sock, "close"):
                sock.close()
        except OSError:
            pass
        return True, "tcp ok"
    except OSError as e:
        return False, "%s" % e


def termux_wifi_up(
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    binary: str = "termux-wifi-connectioninfo",
) -> Tuple[Optional[bool], str]:
    """Optional Termux Wi-Fi check. Returns (None, reason) when unavailable."""
    run = runner or subprocess.run
    try:
        p = run([binary], capture_output=True, text=True, timeout=3)
    except FileNotFoundError:
        return None, "termux-wifi-connectioninfo not found"
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "termux-wifi error: %s" % e
    if p.returncode != 0:
        return None, "termux-wifi rc=%s" % p.returncode
    raw = (p.stdout or "").strip()
    if not raw:
        return None, "termux-wifi empty"
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        return None, "termux-wifi non-json"
    # Termux returns {} when Wi-Fi is off; a connected AP has ssid / ip / network_id.
    if not info:
        return False, "wifi off or empty info"
    ssid = info.get("ssid") or info.get("bssid")
    ip = info.get("ip") or info.get("ipv4")
    if ssid or ip:
        return True, "wifi up"
    # Some builds only set supplicant_state.
    state = (info.get("supplicant_state") or info.get("wifi_state") or "").upper()
    if state in ("COMPLETED", "ENABLED", "CONNECTED"):
        return True, "wifi %s" % state
    if state in ("DISCONNECTED", "INACTIVE", "DISABLED", "INTERFACE_DISABLED"):
        return False, "wifi %s" % state
    return bool(info), "wifi info present"


def probe_connectivity(
    *,
    environ: Optional[dict] = None,
    timeout: float = PROBE_TIMEOUT_DEFAULT,
    connector: Optional[Callable[..., None]] = None,
    wifi_runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    skip_wifi: bool = False,
) -> Dict[str, Any]:
    """Return a probe result dict: online bool, ssh, wifi, reasons."""
    env = os.environ if environ is None else environ
    result: Dict[str, Any] = {
        "when": _now_iso(),
        "online": False,
        "ssh": {"ok": False, "detail": ""},
        "wifi": {"ok": None, "detail": "skipped"},
    }
    try:
        host, port = ssh_probe_target(env)
    except OfflineQueueError as e:
        result["ssh"] = {"ok": False, "detail": str(e)}
        result["online"] = False
        return result
    ok, detail = tcp_reachable(host, port, timeout=timeout, connector=connector)
    # Never echo the real host into logs/state beyond a redacted form.
    result["ssh"] = {"ok": ok, "detail": detail, "port": port}
    wifi_ok: Optional[bool] = None
    wifi_detail = "skipped"
    if not skip_wifi:
        wifi_ok, wifi_detail = termux_wifi_up(runner=wifi_runner)
    result["wifi"] = {"ok": wifi_ok, "detail": wifi_detail}
    # Online when SSH/TCP reaches the fleet. Wi-Fi off alone is not enough to
    # declare offline if TCP still works (USB tether / ethernet). Wi-Fi False
    # with SSH False => offline. Wi-Fi None (non-Termux) ignored.
    if ok:
        result["online"] = True
    elif wifi_ok is False:
        result["online"] = False
    else:
        result["online"] = False
    return result


def load_probe_state(state: Path) -> dict:
    path = state / "probe_state.json"
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode):
            return {"fails": 0}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return {"fails": 0}


def save_probe_state(state: Path, obj: dict, work: Path) -> None:
    _atomic_write_json(state / "probe_state.json", obj, work)


def should_probe_now(state: Path, now: Optional[float] = None) -> Tuple[bool, float]:
    """Respect backoff after consecutive failures. Returns (ok_to_probe, wait_s)."""
    ps = load_probe_state(state)
    fails = int(ps.get("fails") or 0)
    last = float(ps.get("last_probe_epoch") or 0)
    wait = backoff_seconds(fails)
    now = time.time() if now is None else now
    if last and wait and (now - last) < wait:
        return False, wait - (now - last)
    return True, 0.0


# ---------------------------------------------------------------- GitHub (token never logged)


def _github_token(environ: Optional[dict] = None) -> Optional[str]:
    env = os.environ if environ is None else environ
    return (env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or "").strip() or None


def _split_repo(repo: str) -> Tuple[str, str]:
    owner, _, name = repo.partition("/")
    if not owner or not name or "/" in name:
        raise OfflineQueueError("repo must be owner/name")
    return owner, name


def format_comment_body(entry_id: str, body: str) -> str:
    # Scrub secrets/private details from the operator-visible body; marker stays intact.
    safe = scrub_public_text(body.rstrip("\n"))
    return "<!-- familia-offline-queue:id=%s -->\n%s\n" % (entry_id, safe)


def parse_marker(text: str) -> Optional[str]:
    m = MARKER_RE.search(text or "")
    return m.group(1) if m else None


def quotes_marker(text: str, entry_id: str) -> bool:
    """True when *text* quotes our offline-queue marker / entry id."""
    if not text or not entry_id:
        return False
    if ("familia-offline-queue:id=%s" % entry_id) in text:
        return True
    # bare uuid quote (common in short replies)
    if entry_id in text:
        return True
    return False




TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[@-Z\\-_]"
)
_IP_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
_HOSTPORT_RE = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9._-]{0,63}):(\d{2,5})\b"
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_TOKEN_RE = re.compile(
    r"\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_-]{8,}\b"
)
_PRIVHOST_RE = re.compile(
    r"\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0|(?:[A-Za-z0-9-]+\.)+(?:local|lan|internal|home))\b",
    re.IGNORECASE,
)


def reply_allowlist(environ: Optional[dict] = None) -> frozenset:
    """Optional comma-separated logins in FAMILIA_OFFLINE_REPLY_ALLOWLIST."""
    env = os.environ if environ is None else environ
    raw = (env.get("FAMILIA_OFFLINE_REPLY_ALLOWLIST") or "").strip()
    if not raw:
        return frozenset()
    return frozenset(p.strip().lstrip("@") for p in raw.split(",") if p.strip())


def trusted_reply_author(comment: dict, environ: Optional[dict] = None) -> bool:
    """True when author_association is OWNER/MEMBER/COLLABORATOR or login is allowlisted."""
    assoc = (comment.get("author_association") or "").upper()
    if assoc in TRUSTED_ASSOCIATIONS:
        return True
    login = ((comment.get("user") or {}).get("login") or "").strip()
    if login and login.lstrip("@") in reply_allowlist(environ):
        return True
    return False


def strip_controls_escapes(text: str) -> str:
    """Remove C0 controls (keep TAB/LF) and ANSI/CSI escape sequences."""
    if not text:
        return ""
    out = _ANSI_RE.sub("", text)
    out = _CTRL_RE.sub("", out)
    return out


def scrub_public_text(text: str) -> str:
    """Redact IPs, host:port, emails, tokens, and private-looking hostnames."""
    if not text:
        return ""
    out = strip_controls_escapes(text)
    out = _TOKEN_RE.sub("[token]", out)
    out = _EMAIL_RE.sub("[email]", out)
    # host:port before bare IPs so "A.B.C.D:NNNN" becomes "[ip]:[port]"
    out = _HOSTPORT_RE.sub(lambda m: "%s:[port]" % m.group(1), out)
    out = _IP_RE.sub("[ip]", out)
    out = re.sub(r"\[ip\]:\d{2,5}\b", "[ip]:[port]", out)
    out = _PRIVHOST_RE.sub("[host]", out)
    return out


def post_issue_comment(
    repo: str,
    issue: int,
    body: str,
    *,
    environ: Optional[dict] = None,
    http_post: Optional[Callable[..., dict]] = None,
    gh_runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> dict:
    """Post a comment; return {"id": int, "html_url": str, ...}. Never logs the token."""
    if http_post is not None:
        return http_post(repo, issue, body)
    owner, name = _split_repo(repo)
    # Prefer gh when available (uses gh auth, no token in our process env needed).
    run = gh_runner or subprocess.run
    try:
        p = run(
            [
                "gh", "api",
                "repos/%s/%s/issues/%d/comments" % (owner, name, issue),
                "-f", "body=%s" % body,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if p.returncode == 0 and (p.stdout or "").strip():
            return json.loads(p.stdout)
    except FileNotFoundError:
        pass
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    tok = _github_token(environ)
    if not tok:
        raise OfflineQueueError("no gh CLI success and no GITHUB_TOKEN/GH_TOKEN for REST post")
    url = "https://api.github.com/repos/%s/%s/issues/%d/comments" % (
        urllib.parse.quote(owner, safe=""),
        urllib.parse.quote(name, safe=""),
        issue,
    )
    data = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer %s" % tok,
            "Content-Type": "application/json",
            "User-Agent": "familia-offline-queue/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Do not include request headers (token) in the error message.
        raise OfflineQueueError("GitHub POST comment failed: HTTP %s" % e.code) from None
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise OfflineQueueError("GitHub POST comment failed: %s" % e) from None


def list_issue_comments(
    repo: str,
    issue: int,
    *,
    since: Optional[str] = None,
    environ: Optional[dict] = None,
    http_get: Optional[Callable[..., List[dict]]] = None,
    gh_runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> List[dict]:
    if http_get is not None:
        return http_get(repo, issue, since)
    owner, name = _split_repo(repo)
    run = gh_runner or subprocess.run
    q = "per_page=100"
    if since:
        q += "&since=%s" % urllib.parse.quote(since)
    path = "repos/%s/%s/issues/%d/comments?%s" % (owner, name, issue, q)
    try:
        p = run(["gh", "api", path], capture_output=True, text=True, timeout=60)
        if p.returncode == 0 and (p.stdout or "").strip():
            data = json.loads(p.stdout)
            if isinstance(data, list):
                return data
    except FileNotFoundError:
        pass
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    tok = _github_token(environ)
    if not tok:
        raise OfflineQueueError("no gh CLI success and no GITHUB_TOKEN/GH_TOKEN for REST get")
    url = "https://api.github.com/%s" % path
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer %s" % tok,
            "User-Agent": "familia-offline-queue/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, list):
                raise OfflineQueueError("unexpected comments payload")
            return data
    except urllib.error.HTTPError as e:
        raise OfflineQueueError("GitHub GET comments failed: HTTP %s" % e.code) from None
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise OfflineQueueError("GitHub GET comments failed: %s" % e) from None


# ---------------------------------------------------------------- flush / pull


def flush_queue(
    state: Path,
    work: Path,
    *,
    environ: Optional[dict] = None,
    poster: Optional[Callable[..., dict]] = None,
    only_id: Optional[str] = None,
) -> List[dict]:
    """Post queued entries as issue comments. Returns updated entries."""
    updated: List[dict] = []
    for entry in list_entries(state):
        if entry.get("status") != "queued":
            continue
        if only_id and entry.get("id") != only_id:
            continue
        body = format_comment_body(entry["id"], entry["body"])
        try:
            if poster is not None:
                resp = poster(entry["repo"], int(entry["issue"]), body)
            else:
                resp = post_issue_comment(
                    entry["repo"], int(entry["issue"]), body, environ=environ
                )
            entry["status"] = "posted"
            entry["comment_id"] = resp.get("id")
            entry["posted_at"] = resp.get("created_at") or _now_iso()
            entry["last_error"] = None
            entry["html_url"] = resp.get("html_url")
        except OfflineQueueError as e:
            entry["last_error"] = str(e)
            # stay queued
        save_entry(state, entry, work)
        updated.append(entry)
    return updated


def pull_responses(
    state: Path,
    work: Path,
    *,
    environ: Optional[dict] = None,
    getter: Optional[Callable[..., List[dict]]] = None,
) -> List[dict]:
    """For posted entries, fetch later comments that quote our marker; ignore the rest."""
    updated: List[dict] = []
    # Group by (repo, issue) to minimize API calls.
    groups: Dict[Tuple[str, int], List[dict]] = {}
    for entry in list_entries(state):
        if entry.get("status") not in ("posted", "responded"):
            continue
        key = (entry["repo"], int(entry["issue"]))
        groups.setdefault(key, []).append(entry)
    for (repo, issue), entries in groups.items():
        since = None
        posted_times = [e.get("posted_at") for e in entries if e.get("posted_at")]
        if posted_times:
            since = min(posted_times)
        try:
            if getter is not None:
                comments = getter(repo, issue, since)
            else:
                comments = list_issue_comments(repo, issue, since=since, environ=environ)
        except OfflineQueueError as e:
            for entry in entries:
                entry["last_error"] = str(e)
                save_entry(state, entry, work)
                updated.append(entry)
            continue
        by_marker: Dict[str, dict] = {}
        for c in comments:
            mid = parse_marker(c.get("body") or "")
            if mid:
                by_marker[mid] = c
        for entry in entries:
            eid = entry["id"]
            ours = by_marker.get(eid)
            our_id = entry.get("comment_id") or (ours.get("id") if ours else None)
            if ours and not entry.get("comment_id"):
                entry["comment_id"] = ours.get("id")
            responses = []
            response_ids = []
            # Reply only if it quotes our marker/id. Ignore every other later comment.
            our_created = None
            if ours:
                our_created = ours.get("created_at")
            elif entry.get("posted_at"):
                our_created = entry["posted_at"]
            for c in comments:
                cid = c.get("id")
                body = c.get("body") or ""
                if our_id is not None and cid == our_id:
                    continue
                if our_created and (c.get("created_at") or "") < our_created:
                    continue
                # Our own enqueue posts start with the marker for this or another id —
                # those are commands, not replies (even though they "contain" a marker).
                mid = parse_marker(body)
                if mid and body.lstrip().startswith("<!--"):
                    # treat as an enqueue-shaped comment, not a human reply
                    continue
                if not quotes_marker(body, eid):
                    continue
                if not trusted_reply_author(c, environ):
                    continue
                safe_body = scrub_public_text(body)
                responses.append(
                    {
                        "id": cid,
                        "user": ((c.get("user") or {}).get("login")),
                        "author_association": c.get("author_association"),
                        "created_at": c.get("created_at"),
                        "body": safe_body,
                        "html_url": c.get("html_url"),
                    }
                )
                response_ids.append(cid)
            entry["response_comment_ids"] = response_ids
            entry["last_error"] = None
            if responses:
                entry["status"] = "responded"
                rpath = responses_dir(state) / ("%s.json" % eid)
                _atomic_write_json(
                    rpath,
                    {"id": eid, "issue": issue, "repo": repo, "responses": responses},
                    work,
                )
            save_entry(state, entry, work)
            updated.append(entry)
    return updated


# ---------------------------------------------------------------- CLI


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def cmd_probe(args: argparse.Namespace) -> int:
    with RunContext(environ=os.environ) as ctx:
        ok_now, wait = should_probe_now(ctx.state)
        if not ok_now and not args.force:
            _print_json({"skipped": True, "wait_s": round(wait, 1), "reason": "backoff"})
            return 0
        result = probe_connectivity(
            timeout=args.timeout,
            skip_wifi=args.no_wifi,
        )
        ps = load_probe_state(ctx.state)
        if result["online"]:
            ps["fails"] = 0
        else:
            ps["fails"] = int(ps.get("fails") or 0) + 1
        ps["last_probe_epoch"] = time.time()
        ps["last_result"] = {
            "online": result["online"],
            "ssh_ok": result["ssh"]["ok"],
            "wifi_ok": result["wifi"]["ok"],
            "when": result["when"],
        }
        save_probe_state(ctx.state, ps, ctx.work)  # type: ignore[arg-type]
        _print_json(result)
        return 0 if result["online"] else 2


def cmd_enqueue(args: argparse.Namespace) -> int:
    body = args.text
    if body is None:
        body = sys.stdin.read()
    elif isinstance(body, list):
        body = " ".join(body)
    try:
        issue = resolve_issue_number(args.issue)
    except OfflineQueueError as e:
        print("offline_queue: %s" % e, file=sys.stderr)
        return 2
    repo = args.repo or DEFAULT_REPO
    with RunContext(environ=os.environ) as ctx:
        entry = enqueue(
            body,
            issue=issue,
            repo=repo,
            state=ctx.state,
            work=ctx.work,
        )
        _print_json(entry)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with RunContext(environ=os.environ) as ctx:
        entries = list_entries(ctx.state)
        ps = load_probe_state(ctx.state)
        summary = {
            "state_dir": str(ctx.state),
            "counts": {
                "queued": sum(1 for e in entries if e.get("status") == "queued"),
                "posted": sum(1 for e in entries if e.get("status") == "posted"),
                "responded": sum(1 for e in entries if e.get("status") == "responded"),
                "total": len(entries),
            },
            "probe_state": ps,
            "entries": entries if args.verbose else [
                {"id": e["id"], "issue": e["issue"], "status": e["status"], "created_at": e.get("created_at")}
                for e in entries
            ],
        }
        _print_json(summary)
    return 0


def cmd_flush(args: argparse.Namespace) -> int:
    with RunContext(environ=os.environ) as ctx:
        if not args.force:
            result = probe_connectivity(timeout=args.timeout, skip_wifi=args.no_wifi)
            if not result["online"]:
                _print_json({"flushed": [], "online": False, "probe": result})
                return 2
        updated = flush_queue(ctx.state, ctx.work, only_id=args.id)  # type: ignore[arg-type]
        _print_json({"flushed": updated, "online": True})
        # non-zero if any still queued with error
        if any(e.get("status") == "queued" for e in updated):
            return 1
        return 0


def cmd_pull(args: argparse.Namespace) -> int:
    with RunContext(environ=os.environ) as ctx:
        if not args.force:
            result = probe_connectivity(timeout=args.timeout, skip_wifi=args.no_wifi)
            if not result["online"]:
                _print_json({"pulled": [], "online": False, "probe": result})
                return 2
        updated = pull_responses(ctx.state, ctx.work)  # type: ignore[arg-type]
        _print_json({"pulled": updated, "online": True})
        return 0


def cmd_sync(args: argparse.Namespace) -> int:
    with RunContext(environ=os.environ) as ctx:
        result = probe_connectivity(timeout=args.timeout, skip_wifi=args.no_wifi)
        ps = load_probe_state(ctx.state)
        if result["online"]:
            ps["fails"] = 0
        else:
            ps["fails"] = int(ps.get("fails") or 0) + 1
        ps["last_probe_epoch"] = time.time()
        ps["last_result"] = {
            "online": result["online"],
            "ssh_ok": result["ssh"]["ok"],
            "wifi_ok": result["wifi"]["ok"],
            "when": result["when"],
        }
        save_probe_state(ctx.state, ps, ctx.work)  # type: ignore[arg-type]
        if not result["online"]:
            _print_json({"online": False, "probe": result, "flushed": [], "pulled": []})
            return 2
        flushed = flush_queue(ctx.state, ctx.work)  # type: ignore[arg-type]
        pulled = pull_responses(ctx.state, ctx.work)  # type: ignore[arg-type]
        _print_json({"online": True, "probe": result, "flushed": flushed, "pulled": pulled})
        return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="offline_queue.py",
        description="Android offline fallback: queue locally, flush/pull via GitHub issue comments (#332)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_probe_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--timeout", type=float, default=PROBE_TIMEOUT_DEFAULT)
        sp.add_argument("--no-wifi", action="store_true", help="skip termux-wifi-connectioninfo")
        sp.add_argument("--force", action="store_true", help="ignore backoff / skip online check")

    sp = sub.add_parser("probe", help="check SSH/Wi-Fi reachability")
    add_probe_flags(sp)
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("enqueue", help="queue a command for later GitHub post")
    sp.add_argument(
        "--issue",
        type=positive_issue_arg,
        default=None,
        help="GitHub issue number (default: FAMILIA_OFFLINE_ISSUE or %d)" % DEFAULT_ISSUE,
    )
    sp.add_argument("--repo", default=None, help="owner/name (default FAMILIA_OFFLINE_REPO or brianreborn/familia)")
    sp.add_argument("text", nargs="*", default=None, help="command text; omit to read stdin")
    sp.set_defaults(func=cmd_enqueue)

    sp = sub.add_parser("status", help="show queue and probe state")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("flush", help="post queued commands as issue comments when online")
    add_probe_flags(sp)
    sp.add_argument("--id", default=None, help="flush only this entry id")
    sp.set_defaults(func=cmd_flush)

    sp = sub.add_parser("pull", help="pull later issue comments for posted entries")
    add_probe_flags(sp)
    sp.set_defaults(func=cmd_pull)

    sp = sub.add_parser(
        "sync",
        help="operator-run only: probe; if online, flush then pull (no proto_chat auto-queue)",
    )
    add_probe_flags(sp)
    sp.set_defaults(func=cmd_sync)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = build_parser()
    args = p.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except OfflineQueueError as e:
        print("offline_queue: %s" % e, file=sys.stderr)
        return 1
    except rd.RuntimeDirError as e:
        print("offline_queue: state dir refused: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
