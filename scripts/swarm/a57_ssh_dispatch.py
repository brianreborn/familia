#!/usr/bin/env python3
"""Opt-in bounded SSH smoke from the miryam swarm runner to the two A57 phones.

usage: python3 scripts/swarm/a57_ssh_dispatch.py [--job python-compile]
           [--devices both|galaxy1|galaxy2|galaxy1,galaxy2] [--sha HEX]
           [--inventory PATH]

The phones are not GitHub Actions runners. A forge-hosted workflow only gates
trust; the existing miryam runner (labels self-hosted, Linux, swarm-bench,
host:miryam) runs this script. This script opens SSH itself. It does not use
the galaxy1/galaxy2 SSH aliases (those jump via angel). Connection facts,
the pinned known_hosts file, and the identity file live in a private inventory,
never in git. See docs/ci/a57-ssh-dispatch.md.

Exit: 0 every selected device passed; 1 a device was not pass (fail, offline,
timeout, busy, host-key mismatch, or not configured); 2 refused before SSH
(untrusted event, bad argument, unsafe inventory).

Example: A57_SSH_CI_ALLOW_LOCAL=1 python3 scripts/swarm/a57_ssh_dispatch.py --devices galaxy1
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEVICES = ("galaxy1", "galaxy2")
JOB_PYTHON_COMPILE = "python-compile"
OFFICIAL_REPO = "brianreborn/familia"
TRUSTED_REF = "refs/heads/main"
UNTRUSTED_EVENTS = {
    "pull_request",
    "pull_request_target",
    "pull_request_review",
    "pull_request_review_comment",
    "fork",
    "issue_comment",
    "watch",
    "workflow_run",
}
PLACEHOLDER_USERS = frozenset({
    "", "REPLACE_ME", "replace_me", "termux-user", "<termux-user>", "<user>",
})
DOC_NETS = (
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
)
SHARED_TMP = ("/tmp", "/var/tmp", "/dev/shm", "/private/tmp")
TOP_KEYS = frozenset({"schema", "devices"})
DEVICE_KEYS = frozenset({"addr", "port", "user", "known_hosts", "identity_file"})
SECRET_NAME = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTHORIZATION|API_KEY|_KEY)", re.I)
IPV4_TEXT = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
TERMUX_USER_TEXT = re.compile(r"\bu0_a\d+\b")
SHA_TEXT = re.compile(r"[0-9a-fA-F]{7,40}")
# Fixed remote program. No interpolation. Stdin carries this source; the remote
# shell only sees REMOTE_COMMAND. It must not touch resident servers, install
# packages, or open a socket.
REMOTE_COMMAND = "python3 -I -c 'import sys; exec(sys.stdin.buffer.read().decode())'"
REMOTE_SMOKE = r"""
import fcntl
import os
import shutil
import signal
import sys
import tempfile
import py_compile

def _alarm(_signo, _frame):
    raise TimeoutError("alarm")

def main():
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(20)
    fd = None
    held = False
    work = None
    try:
        home = os.path.expanduser("~")
        if not home or home == "~" or not os.path.isdir(home):
            print("fail no-home")
            return 12
        cache = os.path.join(home, ".cache")
        os.makedirs(cache, mode=0o700, exist_ok=True)
        lock_path = os.path.join(cache, "familia-a57-ci.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("busy")
            return 11
        held = True
        print("python " + sys.version.split()[0])
        tmp = os.environ.get("TMPDIR") or cache
        if not tmp or not os.path.isdir(tmp):
            tmp = cache
        work = tempfile.mkdtemp(prefix="familia-a57-smoke-", dir=tmp)
        src = os.path.join(work, "smoke.py")
        pyc = os.path.join(work, "smoke.pyc")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("print(1)\n")
        py_compile.compile(src, cfile=pyc, doraise=True)
        if not os.path.isfile(pyc) or os.path.getsize(pyc) < 1:
            print("fail no-pyc")
            return 12
        print("compile-ok")
        print("pass")
        signal.alarm(0)
        return 0
    except Exception:
        print("fail smoke")
        return 12
    finally:
        signal.alarm(0)
        if work:
            shutil.rmtree(work, ignore_errors=True)
        if held:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        if fd is not None:
            os.close(fd)

raise SystemExit(main())
"""


class DispatchError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Lock:
    def __init__(self, fd: int):
        self.fd = fd

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None


def scrub(text: str) -> str:
    text = IPV4_TEXT.sub("<addr>", text)
    text = TERMUX_USER_TEXT.sub("<user>", text)
    return text


def secret_values(env: dict) -> list[str]:
    found = []
    for key, value in env.items():
        if not value or len(value) < 8:
            continue
        if SECRET_NAME.search(key):
            found.append(value)
    return found


def render(lines: list[str], secrets: list[str]) -> str:
    text = "\n".join(lines) + "\n"
    for secret in secrets:
        if secret and secret in text:
            return "a57-ssh-ci schema=1\noverall=refused reason=secret-leak\n"
    return scrub(text)


def trust_decision(env: dict) -> tuple[bool, str]:
    """Refuse fork PRs, pull_request_target, and any ref other than main.

    A57_SSH_CI_ALLOW_LOCAL=1 permits a manual rerun on the runner host only when
    no GitHub event is set. It does not override an untrusted event.
    """
    event = env.get("GITHUB_EVENT_NAME") or ""
    if event.startswith("pull_request") or event in UNTRUSTED_EVENTS:
        return False, "untrusted-event"
    repo = env.get("GITHUB_REPOSITORY") or ""
    if repo and repo != OFFICIAL_REPO:
        return False, "untrusted-repo"
    head = env.get("GITHUB_HEAD_REPOSITORY") or ""
    if head and head != OFFICIAL_REPO:
        return False, "untrusted-repo"
    ref = env.get("GITHUB_REF") or ""
    if "\n" in ref or "\r" in ref or ref.startswith("refs/pull/"):
        return False, "untrusted-ref"
    event_path = (env.get("GITHUB_EVENT_PATH") or "").strip()
    if event_path and _event_is_untrusted(event_path):
        return False, "untrusted-repo"
    if event in ("push", "workflow_dispatch"):
        if ref != TRUSTED_REF:
            return False, "untrusted-ref"
        if event == "push":
            return True, "push-main"
        return True, "workflow-dispatch"
    if event == "" and env.get("A57_SSH_CI_ALLOW_LOCAL") == "1":
        return True, "local-opt-in"
    if event == "":
        return False, "no-event"
    return False, "untrusted-event"


def _event_is_untrusted(path: str) -> bool:
    """Fail closed if a GitHub event file says this is a fork or a foreign PR head."""
    try:
        if os.path.getsize(path) > 2_000_000:
            return True
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return True
    if not isinstance(data, dict):
        return True
    repo = data.get("repository")
    if isinstance(repo, dict) and repo.get("fork") is True:
        return True
    pr = data.get("pull_request")
    if isinstance(pr, dict):
        head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
        base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
        head_repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
        base_repo = base.get("repo") if isinstance(base.get("repo"), dict) else {}
        head_name = head_repo.get("full_name") or ""
        base_name = base_repo.get("full_name") or ""
        if head_name and base_name and head_name != base_name:
            return True
        if head_repo.get("fork") is True:
            return True
    return False


def parse_devices(text: str) -> list[str]:
    if not isinstance(text, str) or not text or any(c in text for c in "\n\r\x00;&|$`<>\\'\"(){}[]!*?"):
        raise DispatchError("bad-device")
    if text == "both":
        return list(DEVICES)
    parts = [p.strip() for p in text.split(",")]
    if not parts or any(not p for p in parts) or len(parts) != len(set(parts)):
        raise DispatchError("bad-device")
    if any(p not in DEVICES for p in parts):
        raise DispatchError("bad-device")
    return [d for d in DEVICES if d in parts]


def parse_job(job: str) -> str:
    if job != JOB_PYTHON_COMPILE:
        raise DispatchError("bad-job")
    return job


def parse_sha(sha: str) -> str:
    if sha is None or sha == "":
        return ""
    if not isinstance(sha, str) or SHA_TEXT.fullmatch(sha) is None:
        raise DispatchError("bad-sha")
    return sha.lower()


def _bounded(env: dict, key: str, default: float, lo: float, hi: float) -> float:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        raise DispatchError("bad-budget") from None
    if val < lo or val > hi:
        raise DispatchError("bad-budget")
    return val


def _expand(raw: str, env: dict) -> str:
    if not isinstance(raw, str) or not raw or any(c in raw for c in "\n\r\x00"):
        raise DispatchError("bad-inventory")
    if raw.startswith("~/"):
        home = env.get("HOME") or ""
        if not home or any(c in home for c in "\n\r\x00"):
            raise DispatchError("bad-inventory")
        raw = home + raw[1:]
    if not raw.startswith("/"):
        raise DispatchError("bad-inventory")
    if ".." in Path(raw).parts:
        raise DispatchError("bad-inventory")
    return raw


def inventory_path(env: dict, arg: str = "") -> str:
    if arg:
        return _expand(arg, env)
    explicit = (env.get("A57_SSH_CI_INVENTORY") or "").strip()
    if explicit:
        return _expand(explicit, env)
    xdg = (env.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        if not xdg.startswith("/") or any(c in xdg for c in "\n\r\x00"):
            raise DispatchError("bad-inventory")
        return os.path.join(xdg, "familia", "a57-ssh-ci.yaml")
    home = env.get("HOME") or ""
    if not home or any(c in home for c in "\n\r\x00"):
        return ""
    return os.path.join(home, ".config", "familia", "a57-ssh-ci.yaml")


def inventory_file_ok(path: str) -> bool:
    """True when path is a regular file owned by this user, mode 0600 or 0400."""
    if not path or any(c in path for c in "\n\r\x00"):
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        return False
    if st.st_uid != os.geteuid() or st.st_size < 1:
        return False
    return stat.S_IMODE(st.st_mode) in (0o600, 0o400)


def load_inventory(path: str):
    """Return the devices mapping, or None when absent or not safely usable."""
    if not path or not os.path.lexists(path):
        return None
    # Docs promise 0600, owned by the runner user. Fail closed as not-configured.
    if not inventory_file_ok(path):
        return None
    try:
        import yaml
    except ImportError as exc:
        raise DispatchError("no-yaml") from exc
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:
        raise DispatchError("bad-inventory") from exc
    if not isinstance(data, dict) or set(data) - TOP_KEYS or data.get("schema") != 1:
        raise DispatchError("bad-inventory")
    devices = data.get("devices")
    if not isinstance(devices, dict):
        raise DispatchError("bad-inventory")
    return devices


def check_unique_endpoints(devices: dict) -> None:
    """Refuse two inventory entries that share the same (addr, port)."""
    seen: dict[tuple, str] = {}
    for name, raw in devices.items():
        if not isinstance(raw, dict):
            continue
        key = (raw.get("addr"), raw.get("port"))
        if key in seen:
            raise DispatchError("bad-inventory")
        seen[key] = name


def _shared_temp(path: str) -> bool:
    real = os.path.realpath(path)
    for root in SHARED_TMP:
        try:
            base = os.path.realpath(root)
        except OSError:
            base = root
        if real == base or real.startswith(base.rstrip("/") + "/"):
            return True
    return False


def lock_dir(env: dict) -> str:
    raw = (env.get("A57_SSH_CI_LOCK_DIR") or "").strip()
    if raw:
        path = _expand(raw, env) if raw.startswith("~") or raw.startswith("/") else ""
        if not path:
            raise DispatchError("bad-lockdir")
    else:
        # One fixed path under $HOME so a login shell and the runner service
        # share the same locks. Do not default to $XDG_RUNTIME_DIR.
        home = env.get("HOME") or ""
        if not home or any(c in home for c in "\n\r\x00"):
            raise DispatchError("bad-lockdir")
        path = os.path.join(home, ".cache", "familia", "a57-ssh-locks")
    if _shared_temp(path):
        raise DispatchError("bad-lockdir")
    old = os.umask(0o077)
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    finally:
        os.umask(old)
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise DispatchError("bad-lockdir")
    if st.st_uid != os.geteuid():
        raise DispatchError("bad-lockdir")
    if stat.S_IMODE(st.st_mode) & 0o077:
        os.chmod(path, 0o700)
    return path


def acquire_lock(directory: str, device: str, wait_s: float) -> _Lock | None:
    if device not in DEVICES:
        raise DispatchError("bad-device")
    path = os.path.join(directory, device + ".lock")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise DispatchError("bad-lockdir") from exc
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            os.chmod(path, 0o600)
        import fcntl
        deadline = time.monotonic() + max(0.0, wait_s)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return _Lock(fd)
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    fd = -1
                    return None
                time.sleep(0.02)
    except Exception:
        if fd >= 0:
            os.close(fd)
        raise


def _check_file(path: str, kind: str) -> str:
    if any(c in path for c in " \t=\n\r"):
        raise DispatchError("bad-inventory")
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise DispatchError("bad-inventory") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise DispatchError("bad-inventory")
    if st.st_uid != os.geteuid() or st.st_size < 1:
        raise DispatchError("bad-inventory")
    mode = stat.S_IMODE(st.st_mode)
    if kind == "identity":
        if mode & 0o077:
            raise DispatchError("bad-inventory")
    elif mode & 0o022:
        raise DispatchError("bad-inventory")
    return path


def validate_addr(addr) -> str:
    if not isinstance(addr, str):
        raise DispatchError("bad-inventory")
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError as exc:
        raise DispatchError("bad-inventory") from exc
    if ip.version != 4:
        raise DispatchError("bad-inventory")
    if str(ip) != addr:
        raise DispatchError("bad-inventory")
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        raise DispatchError("bad-inventory")
    if any(ip in net for net in DOC_NETS):
        raise DispatchError("not-configured")
    if not ip.is_private:
        raise DispatchError("bad-inventory")
    return str(ip)


def validate_user(user) -> str:
    if not isinstance(user, str) or user in PLACEHOLDER_USERS:
        raise DispatchError("not-configured" if isinstance(user, str) else "bad-inventory")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}", user) is None:
        raise DispatchError("bad-inventory")
    return user


def resolve_device(devices: dict, name: str, env: dict) -> dict:
    raw = devices.get(name)
    if raw is None:
        raise DispatchError("not-configured")
    if not isinstance(raw, dict) or set(raw) - DEVICE_KEYS:
        raise DispatchError("bad-inventory")
    addr = validate_addr(raw.get("addr"))
    user = validate_user(raw.get("user"))
    port = raw.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise DispatchError("bad-inventory")
    known = _check_file(_expand(raw.get("known_hosts"), env), "known_hosts")
    identity = _check_file(_expand(raw.get("identity_file"), env), "identity")
    return {"addr": addr, "user": user, "port": port, "known_hosts": known, "identity_file": identity}


def build_ssh_argv(ssh_bin: str, target: dict) -> list[str]:
    options = [
        ("BatchMode", "yes"),
        ("StrictHostKeyChecking", "yes"),
        ("CheckHostIP", "yes"),
        ("UpdateHostKeys", "no"),
        ("ProxyJump", "none"),
        ("ProxyCommand", "none"),
        ("ForwardAgent", "no"),
        ("ForwardX11", "no"),
        ("ClearAllForwardings", "yes"),
        ("IdentitiesOnly", "yes"),
        ("IdentityAgent", "none"),
        ("PreferredAuthentications", "publickey"),
        ("PasswordAuthentication", "no"),
        ("KbdInteractiveAuthentication", "no"),
        ("NumberOfPasswordPrompts", "0"),
        ("ConnectTimeout", "10"),
        ("ServerAliveInterval", "5"),
        ("ServerAliveCountMax", "2"),
        ("ControlMaster", "no"),
        ("ControlPath", "none"),
        ("RequestTTY", "no"),
        ("LogLevel", "ERROR"),
        ("GlobalKnownHostsFile", "/dev/null"),
        ("UserKnownHostsFile", target["known_hosts"]),
        ("IdentityFile", target["identity_file"]),
    ]
    argv = [ssh_bin, "-F", "/dev/null", "-T", "-p", str(target["port"])]
    for key, value in options:
        argv.extend(["-o", f"{key}={value}"])
    argv.append(f"{target['user']}@{target['addr']}")
    argv.append(REMOTE_COMMAND)
    return argv


def child_env(env: dict, secrets: list[str]) -> dict:
    path = env.get("PATH") or "/usr/bin:/bin"
    home = env.get("HOME") or ""
    if not home or any(c in home for c in "\n\r\x00") or any(c in path for c in "\n\r\x00"):
        raise DispatchError("bad-env")
    tmp = (env.get("TMPDIR") or "").strip()
    if (not tmp or not tmp.startswith("/") or any(c in tmp for c in "\n\r\x00")
            or not os.path.isdir(tmp)):
        tmp = os.path.join(home, ".cache")
    child = {
        "PATH": path,
        "HOME": home,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": tmp,
    }
    blob = "\n".join(child.values())
    for secret in secrets:
        if secret and secret in blob:
            raise DispatchError("secret-leak")
    return child


def resolve_ssh(env: dict) -> str:
    override = (env.get("A57_SSH_CI_SSH") or "").strip()
    if override:
        if env.get("A57_SSH_CI_ALLOW_SSH_OVERRIDE") != "1":
            raise DispatchError("ssh-override-refused")
        if not override.startswith("/") or any(c in override for c in "\n\r\x00"):
            raise DispatchError("ssh-override-refused")
        if not os.path.isfile(override) or not os.access(override, os.X_OK):
            raise DispatchError("ssh-override-refused")
        return override
    found = shutil.which("ssh", path=env.get("PATH"))
    if not found:
        raise DispatchError("no-ssh")
    return found


def classify(rc: int | None, captured: str, timed_out: bool) -> str:
    if timed_out:
        return "timeout"
    if captured and (
        "Host key verification failed" in captured
        or "REMOTE HOST IDENTIFICATION HAS CHANGED" in captured
    ):
        return "hostkey"
    if rc == 0:
        return "pass"
    if rc == 11:
        return "busy"
    if rc == 12:
        return "fail"
    if rc is None or rc < 0 or rc == 255:
        return "unavailable"
    return "fail"


def _killpg(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


_LIVE_PGIDS: set[int] = set()
_LIVE_GUARD = threading.Lock()
_KILL_GRACE = 2.0


class SignalStop(BaseException):
    """The dispatcher received SIGTERM, SIGINT, or SIGHUP."""


def _register_pgid(pid: int) -> None:
    with _LIVE_GUARD:
        _LIVE_PGIDS.add(pid)


def _unregister_pgid(pid: int) -> None:
    with _LIVE_GUARD:
        _LIVE_PGIDS.discard(pid)


def _snapshot_pgids() -> list[int]:
    with _LIVE_GUARD:
        return list(_LIVE_PGIDS)


def _shutdown_children(grace: float | None = None) -> None:
    pids = _snapshot_pgids()
    for pid in pids:
        _killpg(pid, signal.SIGTERM)
    wait = _KILL_GRACE if grace is None else grace
    deadline = time.monotonic() + max(0.0, wait)
    while time.monotonic() < deadline:
        alive = False
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive = True
            except (ProcessLookupError, PermissionError):
                pass
        if not alive:
            break
        time.sleep(0.02)
    for pid in pids:
        _killpg(pid, signal.SIGKILL)


def _handle_stop(_signo, _frame) -> None:
    _shutdown_children(_KILL_GRACE)
    raise SignalStop()


def _install_stop_handlers() -> None:
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, _handle_stop)
        except (ValueError, OSError):
            pass


def _fail_signal(secrets: list[str] | None = None, header: str | None = None) -> int:
    _shutdown_children(_KILL_GRACE)
    lines = [header or "a57-ssh-ci schema=1", "overall=fail reason=signal"]
    _emit(render(lines, secrets or []))
    return 1


def run_ssh(argv: list[str], env: dict, budget: float, grace: float) -> tuple[int | None, str, bool]:
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    _register_pgid(proc.pid)
    timed_out = False
    try:
        try:
            _out, err = proc.communicate(REMOTE_SMOKE.encode(), timeout=budget)
        except subprocess.TimeoutExpired:
            timed_out = True
            _killpg(proc.pid, signal.SIGTERM)
            try:
                _out, err = proc.communicate(timeout=grace)
            except subprocess.TimeoutExpired:
                _killpg(proc.pid, signal.SIGKILL)
                _out, err = proc.communicate()
        captured = b""
        if err:
            captured += err
        if _out:
            captured += b"\n" + _out
        text = captured.decode("utf-8", "replace")
        return proc.returncode, text, timed_out
    finally:
        _unregister_pgid(proc.pid)


def _status_for_reason(reason: str) -> str:
    if reason == "not-configured":
        return "not-configured"
    return "refused"


def run_device(name: str, target_or_reason, ssh_bin: str, child: dict, directory: str,
               budget: float, grace: float, wait_s: float, secrets: list[str]) -> dict:
    if isinstance(target_or_reason, str):
        return {"device": name, "status": _status_for_reason(target_or_reason)}
    lock = None
    try:
        lock = acquire_lock(directory, name, wait_s)
        if lock is None:
            return {"device": name, "status": "busy"}
        argv = build_ssh_argv(ssh_bin, target_or_reason)
        blob = "\n".join(argv)
        for secret in secrets:
            if secret and secret in blob:
                return {"device": name, "status": "refused"}
        rc, captured, timed_out = run_ssh(argv, child, budget, grace)
        return {"device": name, "status": classify(rc, captured, timed_out)}
    except DispatchError as exc:
        return {"device": name, "status": _status_for_reason(exc.reason)}
    except Exception:
        return {"device": name, "status": "refused"}
    finally:
        if lock is not None:
            lock.release()


def overall_of(statuses: list[str]) -> str:
    if statuses and all(s == "pass" for s in statuses):
        return "pass"
    if not statuses or all(s == "refused" for s in statuses):
        return "refused"
    return "fail"


def _emit(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _refused(reason: str, secrets: list[str] | None = None) -> int:
    if reason not in {
        "untrusted-event", "untrusted-repo", "untrusted-ref", "no-event",
        "bad-device", "bad-job", "bad-sha", "bad-budget", "bad-inventory",
        "bad-env", "bad-lockdir", "no-yaml", "no-ssh", "ssh-override-refused",
        "secret-leak", "internal",
    }:
        reason = "internal"
    _emit(render([
        "a57-ssh-ci schema=1",
        f"overall=refused reason={reason}",
    ], secrets or []))
    return 2


def dispatch(argv: list[str] | None = None, env: dict | None = None) -> int:
    env = os.environ if env is None else env
    _install_stop_handlers()
    parser = argparse.ArgumentParser(prog="a57_ssh_dispatch.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job", default=JOB_PYTHON_COMPILE)
    parser.add_argument("--devices", default="both")
    parser.add_argument("--sha", default="")
    parser.add_argument("--inventory", default="")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return 0 if code in (0, None) else 2
    secrets = secret_values(env)
    ok, why = trust_decision(env)
    if not ok:
        return _refused(why, secrets)
    try:
        devices = parse_devices(args.devices)
        job = parse_job(args.job)
        sha = parse_sha(args.sha)
        budget = _bounded(env, "A57_SSH_CI_BUDGET_SEC", 35, 0.2, 60)
        grace = _bounded(env, "A57_SSH_CI_KILL_GRACE_SEC", 2, 0.1, 10)
        wait_s = _bounded(env, "A57_SSH_CI_LOCK_WAIT_SEC", 0, 0, 30)
        path = inventory_path(env, args.inventory)
        inv = load_inventory(path)
        if inv is not None:
            check_unique_endpoints(inv)
        global _KILL_GRACE
        _KILL_GRACE = grace
    except DispatchError as exc:
        return _refused(exc.reason, secrets)
    header = f"a57-ssh-ci schema=1 job={job} trust={why}"
    if sha:
        header += f" sha={sha}"
    if inv is None:
        lines = [header]
        for name in devices:
            lines.append(f"device={name} status=not-configured")
        lines.append("overall=fail")
        _emit(render(lines, secrets))
        return 1
    planned = []
    needs_ssh = False
    for name in devices:
        try:
            planned.append((name, resolve_device(inv, name, env)))
            needs_ssh = True
        except DispatchError as exc:
            planned.append((name, exc.reason))
    ssh_bin = ""
    child: dict = {}
    directory = ""
    if needs_ssh:
        try:
            directory = lock_dir(env)
            ssh_bin = resolve_ssh(env)
            child = child_env(env, secrets)
        except DispatchError as exc:
            return _refused(exc.reason, secrets)
    results = []
    workers = max(1, len(devices))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for name, target in planned:
                futures.append((name, pool.submit(
                    run_device, name, target, ssh_bin, child, directory, budget, grace, wait_s, secrets,
                )))
            for name, fut in futures:
                try:
                    results.append(fut.result())
                except Exception:
                    results.append({"device": name, "status": "refused"})
    except (KeyboardInterrupt, SignalStop):
        return _fail_signal(secrets, header)
    by = {r["device"]: r["status"] for r in results}
    lines = [header]
    statuses = []
    for name in devices:
        status = by.get(name, "refused")
        statuses.append(status)
        lines.append(f"device={name} status={status}")
    overall = overall_of(statuses)
    lines.append(f"overall={overall}")
    _emit(render(lines, secrets))
    if overall == "pass":
        return 0
    if overall == "refused":
        return 2
    return 1


def main(argv: list[str] | None = None) -> int:
    try:
        return dispatch(argv)
    except (KeyboardInterrupt, SignalStop):
        return _fail_signal()
    except DispatchError as exc:
        return _refused(exc.reason)
    except Exception:
        return _refused("internal")


if __name__ == "__main__":
    sys.exit(main())
