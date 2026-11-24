#!/usr/bin/env python3
"""Home catalog for the six equal familia menu items.

usage: python3 scripts/home_catalog.py AREA VERB [--apply] [ARG...]
       python3 scripts/home_catalog.py --list-home
       python3 scripts/home_catalog.py --titles
       python3 scripts/home_catalog.py --verbs

Areas (equal on the home menu): models, harnesses, agents, mcp, tools, apps.
Verbs: install, list, start, stop, status.

The legacy menu runs this same script, so each home action has a CLI command.
list and status read the local graph and catalogs. install, start and stop
print that command unless --apply is given. Nothing here binds a port.
Model start --apply delegates to sh start.sh, which keeps the instance file.
MCP and the app store never open a listener.

example: python3 scripts/home_catalog.py models list
example: python3 scripts/home_catalog.py models start --apply
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import familia_yaml  # noqa: E402

AREAS = (
    ("models", "Models"),
    ("harnesses", "Harnesses"),
    ("agents", "Agents"),
    ("mcp", "MCP servers"),
    ("tools", "Tool sets"),
    ("apps", "App store"),
)
VERBS = ("install", "list", "start", "stop", "status")
AREA_OF = dict(AREAS)
TITLES = tuple(title for _, title in AREAS)
VERBS_TEXT = "install, list, start, stop, status"
LEGACY_GOALS = (
    "Talk to the protomodel",
    "Open llama-ui web cockpit",
    "Find more models",
    "List all models",
    "Configure all graphs",
    "Search my X / Twitter posts",
    "Install / first-time setup",
    "Proving grounds (graded)",
    "Legacy menu",
)
# Local apps the store lists by reference. Keys must exist in menu-items.txt.
APP_ITEMS = (
    ("skills.menu", "bundled skills"),
    ("skills.vendor", "bring in a surveyed skill"),
    ("models.fetch", "download a model"),
    ("models.add", "add a local model file"),
    ("reach.enable", "opt an agent into Agent-Reach"),
    ("reach.mcp", "print an MCP example"),
    ("agents.hermes", "hermes on the coder node"),
    ("harness2.status", "Harness2 mode"),
    ("home.find-models", "find more models"),
    ("home.talk", "talk to the protomodel"),
    ("test.proving-grounds", "graded proving grounds"),
)
def listener_notice():
    """Fixed sentence. No credential value is read or printed."""
    say("Network listeners need an API key. This command does not bind a port.")


def _windows():
    return os.name == "nt" or sys.platform == "win32"


def _have_sh():
    return shutil.which("sh") is not None


def _port():
    raw = os.environ.get("FAMILIA_PORT") or os.environ.get("PORT") or "9931"
    try:
        return int(raw)
    except ValueError:
        return 9931


def _port_wait_seconds():
    """How long Windows start waits for the listen port. Fail closed after this."""
    raw = os.environ.get("FAMILIA_HOME_PORT_WAIT") or "120"
    try:
        n = int(raw)
    except ValueError:
        return 120
    if n < 1:
        return 120
    if n > 600:
        return 600
    return n


def _runtime():
    if _windows():
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local")
        path = os.path.join(base, "familia", "run")
        os.makedirs(path, exist_ok=True)
        return path
    import runtime_dir
    return runtime_dir.runtime_dir()


def _state_path(kind):
    return os.path.join(_runtime(), "home-%s.json" % kind)


class _ApplyLock(object):
    """Serialize --apply for one area. The lock drops when this process exits."""

    def __init__(self, name):
        self.name = name
        self.fd = None

    def __enter__(self):
        path = os.path.join(_runtime(), "home-apply-%s.lock" % self.name)
        if os.name == "nt":
            import msvcrt
            self.fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                os.close(self.fd)
                self.fd = None
                raise
            return self
        if fcntl is None:
            raise OSError("no file lock on this platform")
        import runtime_dir
        self.fd = runtime_dir.open_lock(path)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_a):
        if self.fd is None:
            return False
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            elif fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None
        return False


def _cmdline(pid):
    path = "/proc/%d/cmdline" % pid
    try:
        with open(path, "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _starttime(pid):
    """Linux starttime from /proc/pid/stat (field 22). Empty when /proc is absent."""
    try:
        with open("/proc/%d/stat" % pid, "r", encoding="ascii", errors="replace") as fh:
            data = fh.read()
    except OSError:
        return ""
    cut = data.rfind(")")
    if cut < 0:
        return ""
    fields = data[cut + 2:].split()
    if len(fields) < 20:
        return ""
    return fields[19]


def _alive(pid):
    """True when pid is still the process we can name.

    On Windows os.kill(pid, 0) is not a probe: it can deliver CTRL_C_EVENT
    or terminate the process. Identity (StartTime / proc token) is the check.
    """
    if not pid or int(pid) <= 0:
        return False
    if _windows():
        token, _cmd = process_identity(pid)
        return bool(token)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def save_record(kind, pid, port, cmdline, starttime=None):
    """Store process_identity's token. Refuse when this OS cannot prove one.

    _starttime() is Linux /proc only. Windows and FreeBSD identity comes from
    process_identity, and an empty token is not a stop target.
    """
    token = starttime or ""
    ident_cmd = ""
    if not token:
        token, ident_cmd = process_identity(pid)
        token = token or ""
    if not token:
        return None
    if not cmdline and ident_cmd:
        cmdline = ident_cmd
    doc = {
        "pid": int(pid),
        "port": int(port),
        "starttime": token,
        "cmdline": (cmdline or "")[:240],
        "kind": kind,
    }
    path = _state_path(kind)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="ascii") as fh:
        fh.write(json.dumps(doc, ensure_ascii=True))
        fh.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return doc


def load_record(kind):
    path = _state_path(kind)
    try:
        with open(path, encoding="ascii") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def _ps_identity(pid):
    """FreeBSD/macOS: ps -o lstart=,command=. None when the tool cannot answer."""
    if not shutil.which("ps"):
        return None, None
    try:
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        env["TZ"] = "UTC"
        proc = subprocess.run(
            ["ps", "-o", "lstart=,command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    line = (proc.stdout or "").strip()
    if proc.returncode != 0 or not line:
        return None, None
    # lstart is a date, then the command. Keep the whole line as the token
    # plus the command after the last time field. Start token is the full
    # lstart (stable across exec on BSD; the command may change).
    parts = line.split(None, 5)
    if len(parts) < 5:
        return None, None
    token = " ".join(parts[:5])
    cmd = parts[5] if len(parts) > 5 else ""
    fine = _fine_start(pid, token)
    if fine:
        token = fine
    return token, cmd


def _darwin_start(pid):
    """macOS start time in seconds.microseconds. Empty when this is not Darwin."""
    if sys.platform != "darwin":
        return ""
    try:
        import ctypes
        libc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    except OSError:
        return ""
    PROC_PIDTBSDINFO = 3

    class BSDInfo(ctypes.Structure):
        _fields_ = [
            ("pbi_flags", ctypes.c_uint32),
            ("pbi_status", ctypes.c_uint32),
            ("pbi_xstatus", ctypes.c_uint32),
            ("pbi_pid", ctypes.c_uint32),
            ("pbi_ppid", ctypes.c_uint32),
            ("pbi_uid", ctypes.c_uint32),
            ("pbi_gid", ctypes.c_uint32),
            ("pbi_ruid", ctypes.c_uint32),
            ("pbi_rgid", ctypes.c_uint32),
            ("pbi_svuid", ctypes.c_uint32),
            ("pbi_svgid", ctypes.c_uint32),
            ("reserved", ctypes.c_uint32),
            ("pbi_comm", ctypes.c_char * 16),
            ("pbi_name", ctypes.c_char * 32),
            ("pbi_nfiles", ctypes.c_uint32),
            ("pbi_pgid", ctypes.c_uint32),
            ("pbi_pjobc", ctypes.c_uint32),
            ("e_tdev", ctypes.c_uint32),
            ("e_tpgid", ctypes.c_int32),
            ("pbi_nice", ctypes.c_int32),
            ("pbi_start_tvsec", ctypes.c_uint64),
            ("pbi_start_tvusec", ctypes.c_uint64),
        ]

    info = BSDInfo()
    try:
        n = libc.proc_pidinfo(
            ctypes.c_int(int(pid)), ctypes.c_int(PROC_PIDTBSDINFO),
            ctypes.c_uint64(0), ctypes.byref(info), ctypes.c_int(ctypes.sizeof(info)),
        )
    except (OSError, AttributeError):
        return ""
    if n <= 0 or not info.pbi_start_tvsec:
        return ""
    return "%d.%06d" % (int(info.pbi_start_tvsec), int(info.pbi_start_tvusec))


def _lstart_epoch(token):
    """UTC epoch seconds for a C-locale ps lstart, or None."""
    import calendar
    import time
    try:
        return calendar.timegm(time.strptime(token, "%a %b %d %H:%M:%S %Y"))
    except (TypeError, ValueError):
        return None


def _timeval_usec(blob, sec):
    """Microseconds of the one int64 timeval in blob whose seconds match sec.

    FreeBSD and macOS kinfo store the start as a timeval. More than one
    match, or a second that is not the C-locale lstart, is ignored.
    """
    import struct
    if not blob or sec is None or len(blob) < 16:
        return None
    hits = []
    for i in range(0, len(blob) - 15, 8):
        try:
            got, usec = struct.unpack_from("qq", blob, i)
        except struct.error:
            continue
        if got == sec and 0 <= usec < 1000000:
            hits.append(usec)
    uniq = set(hits)
    if len(uniq) == 1:
        return uniq.pop()
    return None


def _kinfo_start(pid, lstart):
    """seconds.microseconds from kern.proc.pid when it agrees with lstart."""
    sec = _lstart_epoch(lstart)
    if sec is None or not shutil.which("sysctl"):
        return ""
    try:
        proc = subprocess.run(
            ["sysctl", "-b", "kern.proc.pid.%d" % int(pid)],
            capture_output=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    usec = _timeval_usec(proc.stdout or b"", sec)
    if usec is None:
        return ""
    return "%d.%06d" % (sec, usec)


def _fine_start(pid, lstart):
    """Sub-second start token. Empty when this OS cannot prove one."""
    darwin = _darwin_start(pid)
    if darwin:
        return darwin
    if sys.platform.startswith("freebsd") or sys.platform == "darwin":
        return _kinfo_start(pid, lstart)
    return ""


def _follow_windows_server(proc, pidfile, port):
    """Record the server as soon as its pid is known. Do not leave the tree running.

    The launcher handle's poll() is the liveness check. os.kill(pid, 0) is not
    used. Elapsed time is printed. Ctrl-C keeps a recorded pid, or taskkills
    the verified launcher tree, then returns to the menu.
    """
    import time
    limit = _port_wait_seconds()
    started_at = time.time()
    deadline = started_at + limit
    launcher_token = None
    if _windows():
        launcher_token, _cmd = process_identity(proc.pid)
    shown = -1
    try:
        while True:
            elapsed = int(time.time() - started_at)
            if elapsed != shown:
                say("waiting %ss of %ss" % (elapsed, limit))
                shown = elapsed
            written = _read_pidfile(pidfile)
            if written and written != proc.pid:
                target = written
            else:
                child = _windows_server_pid(proc.pid)
                target = child if child and child != proc.pid else 0
            if target:
                saved = _adopt("models", target, port, seconds=2, need_port=False)
                if saved:
                    return 0
            if proc.poll() is not None and not target:
                say("llama-server was not visible; nothing recorded")
                return 0
            if time.time() >= deadline:
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        say("interrupted")
        rec = load_record("models")
        if rec and same_process(rec):
            say("recorded pid kept")
            return 0
        if proc.poll() is None:
            _taskkill_launcher(proc, launcher_token)
        say("interrupted; staying in the menu")
        return 0
    if proc.poll() is not None:
        say("llama-server was not visible; nothing recorded")
        return 0
    if _taskkill_launcher(proc, launcher_token):
        say("server did not become recordable in time; stopping the detached tree")
    else:
        say("launcher identity could not be verified; not signaling")
    return 1


def _taskkill_launcher(proc, token):
    """taskkill /T only while this Popen is still the launcher we started."""
    if proc.poll() is not None:
        return False
    if _windows():
        now, _cmd = process_identity(proc.pid)
        if not token or now != token:
            say("pid %s identity changed; not signaling" % proc.pid)
            return False
        return _end_process(proc.pid, expect_token=token)
    return _end_process(proc.pid)


def _wait_server_pid(pidfile, parent, seconds=15):
    """Pid start.bat wrote, or the llama-server child, within a bounded wait.

    The lookup used to run once, while start.bat was still in the license
    and auth guard, so it recorded nothing.
    """
    import time
    deadline = time.time() + seconds
    while True:
        written = _read_pidfile(pidfile)
        if written and written != parent:
            return written
        child = _windows_server_pid(parent)
        if child and child != parent:
            return child
        if time.time() >= deadline:
            return 0
        time.sleep(0.25)


def _windows_server_pid(parent):
    """Pid of llama-server.exe under parent, or 0. Fail closed when the tool is missing."""
    if not _windows() or not shutil.which("powershell"):
        return 0
    script = (
        "$root=%d; "
        "$names='llama-server.exe','llama-server'; "
        "$all=@(Get-CimInstance Win32_Process); "
        "$byid=@{}; foreach($p in $all){ $byid[$p.ProcessId]=$p }; "
        "foreach($p in $all){ if($names -notcontains $p.Name){ continue }; "
        "$cur=$p; $guard=0; while($cur -and $guard -lt 20){ "
        "if($cur.ProcessId -eq $root){ $p.ProcessId; return }; "
        "$cur=$byid[$cur.ParentProcessId]; $guard++ } }"
    ) % int(parent)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    line = (proc.stdout or "").strip().split()
    if proc.returncode != 0 or not line:
        return 0
    try:
        return int(line[0])
    except ValueError:
        return 0


def _windows_identity(pid):
    if not shutil.which("powershell"):
        return None, None
    script = (
        "$p = Get-Process -Id %d -ErrorAction Stop; "
        "$p.StartTime.ToFileTimeUtc().ToString('D', [Globalization.CultureInfo]::InvariantCulture) + '|' + $p.ProcessName"
    ) % pid
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    line = (proc.stdout or "").strip()
    if proc.returncode != 0 or "|" not in line:
        return None, None
    token, _, name = line.partition("|")
    return token.strip(), name.strip()


def process_identity(pid):
    """(start_token, cmdline). (None, None) when this OS cannot prove identity.

    Linux starttime survives exec. Windows uses the process StartTime.
    FreeBSD and macOS use ps lstart, and macOS replaces that with the
    microsecond start from libproc when it is available. Empty means fail
    closed: do not signal.
    """
    if _windows():
        return _windows_identity(pid)
    if os.path.exists("/proc/%d/stat" % pid):
        token = _starttime(pid)
        cmd = _cmdline(pid)
        if token and cmd:
            return token, cmd
    system = os.uname().sysname if hasattr(os, "uname") else ""
    if system in ("FreeBSD", "Darwin", "Linux"):
        return _ps_identity(pid)
    return None, None


def same_process(rec):
    """True when the recorded pid is still the process we started.

    Start time is the identity and survives exec (sh start.sh -> serve.sh).
    A missing token fails closed. A reused pid has a different start time.
    """
    if not rec:
        return False
    try:
        pid = int(rec.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if not _alive(pid):
        return False
    started = rec.get("starttime") or ""
    if not started:
        return False
    token, _cmd = process_identity(pid)
    if not token:
        return False
    return token == started


def _children():
    kids = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return kids
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/status" % name, encoding="ascii", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        ppid = None
        for line in text.splitlines():
            if line.startswith("PPid:"):
                try:
                    ppid = int(line.split()[1])
                except (IndexError, ValueError):
                    ppid = None
                break
        if ppid is not None:
            kids.setdefault(ppid, []).append(int(name))
    return kids


def descendants(pid):
    kids = _children()
    out = []
    stack = list(kids.get(pid, []))
    seen = set()
    while stack:
        child = stack.pop()
        if child in seen:
            continue
        seen.add(child)
        out.append(child)
        stack.extend(kids.get(child, []))
    return out


def _end_process(pid, expect_token=None):
    """Stop pid. On Windows, taskkill /T only after the start token still matches."""
    if _windows():
        now, _cmd = process_identity(pid)
        if not now:
            say("pid %s identity could not be verified; not signaling" % pid)
            return False
        if expect_token is not None and now != expect_token:
            say("pid %s identity changed; not signaling" % pid)
            return False
        try:
            proc = subprocess.run(
                ["taskkill", "/T", "/PID", str(int(pid)), "/F"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            say("pid %s: %s" % (pid, exc))
            return False
        if proc.returncode != 0:
            say("pid %s: taskkill failed" % pid)
            return False
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        say("pid %s: %s" % (pid, exc))
        return False
    return True


def stop_recorded(kind):
    """Signal the recorded pid after a fresh identity check.

    The cmdline must still be a server, or the pid must be listening on the
    recorded port. On Windows the signal is taskkill /T so the server child
    dies with the launcher. The record stays until this pid is gone.
    """
    rec = load_record(kind)
    if not same_process(rec):
        say("nothing to stop")
        if rec:
            say("recorded pid %s port %s is not the process this menu started" % (
                rec.get("pid"), rec.get("port")))
            if not (rec.get("starttime") or ""):
                say("identity was not recorded; refusing to signal")
        else:
            say("no %s process recorded by this menu" % kind)
        return 0
    pid = int(rec["pid"])
    started, cmd = process_identity(pid)
    if not started or started != rec.get("starttime"):
        say("identity changed before the signal; nothing signaled")
        return 0
    port = rec.get("port") or 0
    if not _may_signal(started, cmd, pid, port):
        say("pid %s is not a server and is not listening; nothing signaled" % pid)
        return 0
    extras = _extra_stop_targets(pid, port, started)
    if not _end_process(pid, expect_token=started):
        return 1
    _signal_group(pid)
    for extra, extra_token in extras:
        if extra == pid:
            continue
        now, _cmd = process_identity(extra)
        if not now or now != extra_token:
            say("pid %s identity changed; not signaling" % extra)
            continue
        try:
            os.kill(extra, signal.SIGTERM)
        except OSError:
            pass
    say("signaled pid %s" % pid)
    if port and _port_still_open(port, seconds=5):
        owner = _listen_owner(port) or pid
        say("still listening (pid %s)" % owner)
        return 1
    import time
    time.sleep(0.2)
    if _alive(pid) and same_process(rec):
        say("pid %s still running; record kept" % pid)
        return 0
    try:
        os.remove(_state_path(kind))
    except OSError:
        pass
    say("stopped %s pid %s port %s" % (kind, pid, rec.get("port")))
    return 0


def _extra_stop_targets(pid, port, recorded_token):
    """Descendants of this launch, and the port owner only if it is that launch.

    A server-named process on the port with a different start token is not
    this menu's process. Each descendant is signaled later only if its own
    start token is unchanged.
    """
    found = []
    seen = set()
    if not _windows():
        for child in descendants(pid):
            token, _cmd = process_identity(child)
            if token and child not in seen:
                found.append((child, token))
                seen.add(child)
    owner = _listen_owner(port)
    if owner and owner != pid and owner not in seen:
        token, _cmd = process_identity(owner)
        if token and token == recorded_token:
            found.append((owner, token))
    return found


def _signal_group(pid):
    """Signal the recorded leader's group, never pid 1 and never our own group."""
    if _windows():
        return
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if pid <= 1:
        return
    try:
        pgid = os.getpgid(pid)
        mine = os.getpgrp()
    except OSError:
        return
    if pgid <= 1 or pgid == mine or pgid != pid:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        return


def _port_still_open(port, seconds):
    """True when something is still listening after a bounded wait."""
    import time
    deadline = time.time() + seconds
    while True:
        linux_listener = _linux_port_listening(port)
        if linux_listener is not None:
            if not linux_listener:
                return False
        elif not _listen_owner(port):
            return False
        if time.time() >= deadline:
            return True
        time.sleep(0.1)


def _linux_port_listening(port):
    """Return whether Linux reports a LISTEN socket, independent of PID visibility."""
    if not sys.platform.startswith("linux") or not port:
        return None
    port_hex = "%04X" % int(port)
    saw_table = False
    for name in ("tcp", "tcp6"):
        try:
            with open("/proc/net/%s" % name, encoding="ascii", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        saw_table = True
        for line in lines[1:]:
            fields = line.split()
            if len(fields) >= 4 and fields[1].endswith(":" + port_hex) and fields[3] == "0A":
                return True
    return False if saw_table else None


def describe_record(kind):
    rec = load_record(kind)
    if not rec:
        say("no %s process recorded by this menu" % kind)
        return
    pid = rec.get("pid")
    port = rec.get("port")
    if same_process(rec):
        say("recorded pid %s port %s alive" % (pid, port))
    else:
        say("recorded pid %s port %s is not running as the process this menu started" % (pid, port))


def ascii_fold(text):
    """Chrome is 7-bit. User text that is not ASCII becomes '?'."""
    out = []
    for ch in str(text):
        o = ord(ch)
        if ch in "\n\t" or 32 <= o < 127:
            out.append(ch)
        else:
            out.append("?")
    return "".join(out)


def say(text=""):
    print(ascii_fold(text))


def graph_path():
    return os.environ.get("FAMILIA_GRAPH") or os.path.join(ROOT, "graph.yaml")


def load_graph():
    path = graph_path()
    if not os.path.isfile(path):
        say("graph: missing %s" % path)
        return None
    try:
        doc = familia_yaml.load(path)
    except Exception as exc:  # noqa: BLE001 - show the reader error, stay ASCII
        say("graph: could not read %s (%s)" % (path, exc))
        return None
    if not isinstance(doc, dict):
        say("graph: %s is not a mapping" % path)
        return None
    return doc


def section(doc, name):
    block = doc.get(name) or {}
    if not isinstance(block, dict):
        return {}
    return {k: v for k, v in block.items() if isinstance(k, str)}


def menu_names():
    path = os.path.join(ROOT, "scripts", "menu-items.txt")
    keys = set()
    try:
        lines = open(path, encoding="utf-8")
    except OSError:
        return keys
    with lines as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            keys.add(line.split("|", 1)[0])
    return keys


def cli(area, verb):
    return "python3 scripts/home_catalog.py %s %s" % (area, verb)


def header(area, verb):
    say("%s %s" % (AREA_OF[area], verb))
    say("CLI: %s" % cli(area, verb))


def not_applied(area, verb, detail, notice=True):
    header(area, verb)
    say(detail)
    say("Not applied. Re-run with --apply to do it.")
    if notice:
        listener_notice()
    return 0


def screen_session(name="familia-server"):
    if shutil.which("screen") is None:
        return "screen-not-installed"
    try:
        proc = subprocess.run(
            ["screen", "-ls"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    blob = (proc.stdout or "") + (proc.stderr or "")
    if re.search(r"\d+\." + re.escape(name) + r"\b", blob):
        return "present"
    return "absent"


def log_lines():
    for rel in (".cache/server.log", ".cache/graph.log"):
        path = os.path.join(ROOT, rel)
        if os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            say("log: %s (%d bytes)" % (rel, size))
        else:
            say("log: %s (absent)" % rel)


def catalog_skills():
    path = os.path.join(ROOT, "skills", "catalog.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        say("skills catalog: %s" % exc)
        return []
    out = []
    for row in doc.get("skills") or []:
        if isinstance(row, dict) and row.get("id"):
            out.append(str(row["id"]))
    return out


def cache_file():
    base = os.environ.get("XDG_CACHE_HOME")
    if not base:
        home = os.environ.get("HOME") or os.path.expanduser("~")
        base = os.path.join(home, ".cache")
    return os.path.join(base, "familia", "app-catalog.json")


# --- models -----------------------------------------------------------------

def models_list(_apply, _extra):
    header("models", "list")
    doc = load_graph()
    if doc is None:
        return 1
    names = list(section(doc, "models"))
    say("count: %d in %s" % (len(names), graph_path()))
    for name in names:
        say("  %s" % name)
    say("CLI for one download: familia model fetch ORG/NAME")
    return 0


def models_status(_apply, _extra):
    header("models", "status")
    doc = load_graph()
    if doc is None:
        return 1
    say("count: %d" % len(section(doc, "models")))
    describe_record("models")
    say("screen familia-server: %s (informational; stop follows the recorded pid and port)" % screen_session())
    log_lines()
    listener_notice()
    return 0


def plain_arg(value, label):
    """Refuse option-looking values and cmd.exe metacharacters."""
    if not isinstance(value, str) or not value or value.startswith("-"):
        say("refusing %s that is empty or starts with -" % label)
        return None
    if any(ch in value for ch in "&|;<>`$\n\r"):
        say("refusing %s with shell metacharacters" % label)
        return None
    return value


def safe_extras(values, label):
    out = []
    for value in values:
        item = plain_arg(value, label)
        if item is None:
            return None
        out.append(item)
    return out


def _run_checked(argv):
    """Run argv. A missing interpreter is a message, not a traceback."""
    if not argv or not shutil.which(argv[0]):
        say("cannot run %s: program not on PATH" % (argv[0] if argv else "?"))
        return 1
    try:
        proc = subprocess.run(argv, cwd=ROOT)
    except OSError as exc:
        say("cannot run %s: %s" % (argv[0], exc))
        return 1
    return proc.returncode


def models_install(apply, extra):
    if not apply:
        return not_applied(
            "models", "install",
            "Installs one Hugging Face repo. The menu asks for ORG/NAME.",
        )
    if not extra:
        header("models", "install")
        say("Need a repo: --apply ORG/NAME")
        return 2
    repo = plain_arg(extra[0], "repo")
    rest = safe_extras(extra[1:], "repo argument")
    if repo is None or rest is None:
        return 2
    header("models", "install")
    if _windows():
        say("running: python scripts\\add_model.py --fetch %s" % repo)
        return _run_checked([sys.executable, os.path.join(ROOT, "scripts", "add_model.py"),
                             "--fetch", repo, *rest])
    say("running: scripts/add-model.sh --fetch %s" % repo)
    return _run_checked(["sh", os.path.join(ROOT, "scripts", "add-model.sh"),
                         "--fetch", repo, *rest])


def _remember_started(blob, kind):
    match = re.search(r"PID:\s*(\d+)", blob)
    if not match:
        say("no PID in launcher output; nothing recorded")
        return
    pid = int(match.group(1))
    cmd = _cmdline(pid) or kind
    if save_record(kind, pid, _port(), cmd) is None:
        say("pid %s identity could not be stored; not recording a stop target" % pid)
        return
    say("recorded pid %s port %s" % (pid, _port()))


_SERVER_MARK = ("start.sh", "serve.sh", "start_graph.py", "llama-server", "start.bat")


def _server_cmdline(cmd):
    text = cmd or ""
    return any(mark in text for mark in _SERVER_MARK)


def _coarse_clock(token):
    """True for a 1-second ps lstart. Tick counts and file times are digits."""
    text = token or ""
    if not text:
        return True
    return any(ch.isalpha() for ch in text)


def _field_port(field, port):
    try:
        port_s = str(int(port))
    except (TypeError, ValueError):
        return False
    return (field or "").endswith(":" + port_s)


def _column_pid(fields, pid_index, port):
    """Pid from one column when some field is the local port. 0 if it is not."""
    if len(fields) <= pid_index:
        return 0
    if fields[0] in ("USER", "COMMAND"):
        return 0
    if not any(_field_port(field, port) for field in fields):
        return 0
    try:
        return int(fields[pid_index])
    except ValueError:
        return 0


def _line_is_listener(line, pid, port, kind):
    """True when the pid column of a sockstat or lsof line is this pid.

    sockstat: USER COMMAND PID ... so the pid is column 3.
    lsof: COMMAND PID ... so the pid is column 2.
    A pid that only appears in another column does not match.
    """
    fields = (line or "").split()
    try:
        want = int(pid)
    except (TypeError, ValueError):
        return False
    if kind == "sockstat":
        return _column_pid(fields, 2, port) == want
    if kind == "lsof":
        return _column_pid(fields, 1, port) == want
    return False


def _tool_listens(pid, port):
    commands = []
    if shutil.which("sockstat"):
        commands.append(["sockstat", "-l", "-P", "tcp", "-p", str(int(port))])
    if shutil.which("lsof"):
        commands.append(["lsof", "-nP", "-iTCP:%d" % int(port), "-sTCP:LISTEN"])
    for argv in commands:
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        kind = "sockstat" if argv[0] == "sockstat" else "lsof"
        for line in (proc.stdout or "").splitlines():
            if _line_is_listener(line, pid, port, kind):
                return True
    return False


def _may_signal(token, cmd, pid, port):
    """A one-second clock plus a cmdline marker is not enough to signal.

    The pid must hold the recorded port, or the start token must be finer
    than one second and the command must still be a server.
    """
    if _pid_listens(pid, port):
        return True
    if _server_cmdline(cmd) and not _coarse_clock(token):
        return True
    return False


def _windows_owns_port(pid, port):
    """True when Windows says this pid is listening on port."""
    if not _windows() or not shutil.which("powershell"):
        return False
    script = (
        "$hits = @(Get-NetTCPConnection -LocalPort %d -State Listen "
        "-ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq %d }); "
        "if ($hits.Count -gt 0) { 'yes' }"
    ) % (int(port), int(pid))
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and "yes" in (proc.stdout or "")


def _pid_listens(pid, port):
    """True when this pid holds a TCP listener on port. False if we cannot see one."""
    if not pid or not port:
        return False
    if _windows():
        return _windows_owns_port(pid, port)
    port_hex = "%04X" % int(port)
    inodes = set()
    saw_proc = False
    for name in ("tcp", "tcp6"):
        path = "/proc/net/%s" % name
        try:
            lines = open(path, encoding="ascii", errors="replace").read().splitlines()
        except OSError:
            continue
        saw_proc = True
        for line in lines[1:]:
            fields = line.split()
            if len(fields) < 10:
                continue
            local = fields[1]
            if not local.endswith(":" + port_hex):
                continue
            if fields[3] != "0A":  # LISTEN
                continue
            inodes.add(fields[9])
    if not saw_proc:
        return _tool_listens(pid, port)
    if not inodes:
        return False
    fd_dir = "/proc/%d/fd" % pid
    try:
        fds = os.listdir(fd_dir)
    except OSError:
        return False
    for fd in fds:
        try:
            target = os.readlink(os.path.join(fd_dir, fd))
        except OSError:
            continue
        if target.startswith("socket:[") and target[8:-1] in inodes:
            return True
    return False


def _listen_owner(port):
    """Pid listening on port, or 0 when the port is closed or not visible."""
    if not port:
        return 0
    if _windows():
        return _windows_listen_owner(port)
    port_hex = "%04X" % int(port)
    inodes = set()
    saw = False
    for name in ("tcp", "tcp6"):
        path = "/proc/net/%s" % name
        try:
            lines = open(path, encoding="ascii", errors="replace").read().splitlines()
        except OSError:
            continue
        saw = True
        for line in lines[1:]:
            fields = line.split()
            if len(fields) < 10:
                continue
            if not fields[1].endswith(":" + port_hex) or fields[3] != "0A":
                continue
            inodes.add(fields[9])
    if saw:
        if not inodes:
            return 0
        try:
            names = os.listdir("/proc")
        except OSError:
            return 0
        for name in names:
            if not name.isdigit():
                continue
            pid = int(name)
            fd_dir = "/proc/%s/fd" % name
            try:
                fds = os.listdir(fd_dir)
            except OSError:
                continue
            for fd in fds:
                try:
                    target = os.readlink(os.path.join(fd_dir, fd))
                except OSError:
                    continue
                if target.startswith("socket:[") and target[8:-1] in inodes:
                    return pid
        return 0
    return _tool_listen_owner(port)


def _tool_listen_owner(port):
    if shutil.which("sockstat"):
        try:
            proc = subprocess.run(
                ["sockstat", "-l", "-P", "tcp", "-p", str(int(port))],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None:
            for line in (proc.stdout or "").splitlines():
                found = _column_pid(line.split(), 2, port)
                if found:
                    return found
    if shutil.which("lsof"):
        try:
            proc = subprocess.run(
                ["lsof", "-nP", "-iTCP:%d" % int(port), "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return 0
        for line in (proc.stdout or "").splitlines():
            found = _column_pid(line.split(), 1, port)
            if found:
                return found
    return 0


def _windows_listen_owner(port):
    if not shutil.which("powershell"):
        return 0
    script = (
        "$c = Get-NetTCPConnection -LocalPort %d -State Listen "
        "-ErrorAction SilentlyContinue | Select-Object -First 1 "
        "-ExpandProperty OwningProcess; if ($null -ne $c) { $c }"
    ) % int(port)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    line = (proc.stdout or "").strip().split()
    if proc.returncode != 0 or not line:
        return 0
    try:
        return int(line[0])
    except ValueError:
        return 0


def _adopt(kind, pid, port, seconds=2, need_port=False):
    """Record pid only when this launch's process is a server or holds the port.

    seconds bounds the wait. Windows passes need_port so a slow listener is
    recorded when the port opens, not after a fixed two-second glance.
    """
    import time
    saved = None
    saw = False
    deadline = time.time() + seconds
    while True:
        started, cmd = process_identity(pid)
        listening = _pid_listens(pid, port)
        ready = listening or (not need_port and _may_signal(started, cmd, pid, port))
        if started and ready:
            saw = True
            saved = save_record(kind, pid, port, cmd or "", starttime=started)
            break
        if time.time() >= deadline:
            break
        time.sleep(0.25)
    if not saved:
        if saw:
            say("pid %s identity could not be stored; not recording a stop target" % pid)
        else:
            say("pid %s is not a server from this launch; not recording a stop target" % pid)
        return None
    say("recorded pid %s port %s" % (pid, port))
    return saved


def _pid_from_this_launch(path, begun):
    try:
        st = os.stat(path)
    except OSError:
        return 0
    if st.st_mtime + 1 < begun:
        return 0
    return _read_pidfile(path)


def _read_pidfile(path):
    try:
        with open(path, encoding="ascii") as fh:
            return int(fh.read().strip().split()[0])
    except (OSError, ValueError, IndexError):
        return 0


def models_start(apply, extra):
    if not apply:
        return not_applied(
            "models", "start",
            "Delegates to sh start.sh with DETACH_MODE=nohup (Windows: scripts\\windows\\start.bat, detached). "
            "Network listeners need an API key; this start binds with --api-key-file. "
            "License prompts stay on this terminal. "
            "This menu records a pid only when this launch writes one and the process is a server.",
            notice=False,
        )
    rest = safe_extras(extra, "start argument")
    if rest is None:
        return 2
    header("models", "start")
    say("Network listeners need an API key; this start binds with --api-key-file.")
    if _windows():
        bat = os.path.join(ROOT, "scripts", "windows", "start.bat")
        say("running detached: scripts\\windows\\start.bat")
        if not os.path.isfile(bat):
            say("start.bat is missing")
            return 1
        say("license gate on this terminal, then start.bat detaches")
        try:
            gate = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "licenses.py"), "gate"],
                cwd=ROOT,
            )
        except OSError as exc:
            say("cannot run the license gate: %s" % exc)
            return 1
        if gate.returncode != 0:
            say("licenses not accepted; nothing started")
            return gate.returncode
        try:
            pidfile = os.path.join(_runtime(), "home-models.pid")
        except OSError as exc:
            say("no runtime dir for the pid file: %s" % exc)
            return 1
        try:
            os.remove(pidfile)
        except OSError:
            pass
        log_path = os.path.join(_runtime(), "start-bat.log")
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        env = dict(os.environ)
        env["FAMILIA_PIDFILE"] = pidfile
        try:
            log = open(log_path, "ab")
            proc = subprocess.Popen(
                ["cmd", "/c", bat],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=flags, close_fds=True,
            )
        except OSError as exc:
            say("cannot run start.bat: %s" % exc)
            return 1
        say("detached pid %s" % proc.pid)
        return _follow_windows_server(proc, pidfile, _port())
    say("running: DETACH_MODE=nohup sh start.sh")
    if not _have_sh():
        say("sh is not on PATH. On Windows run scripts\\windows\\start.bat.")
        return 1
    env = dict(os.environ)
    env["DETACH_MODE"] = "nohup"
    try:
        pidfile = os.path.join(_runtime(), "home-models.pid")
    except OSError as exc:
        say("no runtime dir for the pid file: %s" % exc)
        return 1
    try:
        os.remove(pidfile)
    except OSError:
        pass
    env["FAMILIA_PIDFILE"] = pidfile
    argv = ["sh", os.path.join(ROOT, "start.sh")]
    begun = __import__("time").time()
    try:
        proc = subprocess.run(argv + rest, cwd=ROOT, env=env)
    except OSError as exc:
        say("cannot run start.sh: %s" % exc)
        return 1
    if proc.returncode != 0:
        return proc.returncode
    pid = _pid_from_this_launch(pidfile, begun)
    if not pid:
        say("this launch did not write a pid file; nothing recorded")
        return 0
    if _adopt("models", pid, _port()) is None:
        try:
            os.remove(pidfile)
        except OSError:
            pass
        return 0
    return 0


def models_stop(apply, _extra):
    if not apply:
        return not_applied(
            "models", "stop",
            "Signals the pid this menu recorded for the model server, after checking starttime and cmdline. "
            "It does not quit every familia-server screen session.",
        )
    header("models", "stop")
    return stop_recorded("models")


# --- harnesses --------------------------------------------------------------

def harness_rows(doc):
    rows = []
    for name, spec in section(doc, "harnesses").items():
        kind = spec.get("kind") if isinstance(spec, dict) else ""
        rows.append((name, "harnesses", str(kind or "")))
    for name, spec in section(doc, "self_improve").items():
        mode = ""
        if isinstance(spec, dict):
            mode = str(spec.get("mode") or "")
        rows.append((name, "self_improve", mode))
    return rows


def harnesses_list(_apply, _extra):
    header("harnesses", "list")
    doc = load_graph()
    if doc is None:
        return 1
    rows = harness_rows(doc)
    say("count: %d" % len(rows))
    for name, where, detail in rows:
        say("  %s  %s  %s" % (name, where, detail))
    say("CLI for mode: python3 scripts/harness2.py status")
    return 0


def harnesses_status(_apply, _extra):
    return harnesses_list(False, [])


def harnesses_install(apply, extra):
    if not apply:
        return not_applied(
            "harnesses", "install",
            "Fetches the pinned Harness2 source: python3 scripts/harness2.py install.",
        )
    header("harnesses", "install")
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "harness2.py"), "install", *extra],
        cwd=ROOT,
    )
    return proc.returncode


def harnesses_start(apply, extra):
    if not apply:
        return not_applied(
            "harnesses", "start",
            "Sets propose mode: python3 scripts/harness2.py set --agent AGENT --mode propose.",
        )
    if len(extra) < 1:
        header("harnesses", "start")
        say("Need an agent: --apply AGENT")
        return 2
    agent = plain_arg(extra[0], "agent")
    rest = safe_extras(extra[1:], "agent argument")
    if agent is None or rest is None:
        return 2
    header("harnesses", "start")
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "harness2.py"),
         "set", "--agent", agent, "--mode", "propose", *rest],
        cwd=ROOT,
    )
    return proc.returncode


def harnesses_stop(apply, extra):
    if not apply:
        return not_applied(
            "harnesses", "stop",
            "Sets mode off: python3 scripts/harness2.py set --agent AGENT --mode off.",
        )
    if len(extra) < 1:
        header("harnesses", "stop")
        say("Need an agent: --apply AGENT")
        return 2
    agent = plain_arg(extra[0], "agent")
    rest = safe_extras(extra[1:], "agent argument")
    if agent is None or rest is None:
        return 2
    header("harnesses", "stop")
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "harness2.py"),
         "set", "--agent", agent, "--mode", "off", *rest],
        cwd=ROOT,
    )
    return proc.returncode


# --- agents -----------------------------------------------------------------

def agents_list(_apply, _extra):
    header("agents", "list")
    doc = load_graph()
    if doc is None:
        return 1
    rows = section(doc, "agents")
    say("count: %d" % len(rows))
    for name, spec in rows.items():
        kind = host = ""
        if isinstance(spec, dict):
            kind = str(spec.get("kind") or "")
            host = str(spec.get("host") or "")
        say("  %s  kind=%s  host=%s" % (name, kind, host))
    say("CLI: familia hermes")
    say("CLI: familia hermes webapp")
    say("CLI: familia hermes desktop")
    say("CLI: familia guardian weights")
    say("CLI: familia guardian-launch-test")
    return 0


def agents_status(_apply, _extra):
    header("agents", "status")
    doc = load_graph()
    if doc is None:
        return 1
    for name, spec in section(doc, "agents").items():
        skills = []
        if isinstance(spec, dict) and isinstance(spec.get("skills"), list):
            skills = [str(s) for s in spec["skills"]]
        say("  %s  skills=%d" % (name, len(skills)))
    listener_notice()
    return 0


def agents_install(apply, extra):
    if not apply:
        return not_applied(
            "agents", "install",
            "Renders hermes config and starts nothing: scripts/hermes.sh --render-only.",
        )
    header("agents", "install")
    if not _have_sh():
        say("sh is not on PATH, so scripts/hermes.sh was not started.")
        return 1
    return _run_checked(["sh", os.path.join(ROOT, "scripts", "hermes.sh"), "--render-only", *extra])


def agents_start(apply, extra):
    if not apply:
        return not_applied(
            "agents", "start",
            "Runs scripts/hermes.sh on this terminal (license review stays visible). "
            "Stop does not end that foreground session and does not stop model servers.",
        )
    header("agents", "start")
    listener_notice()
    if not _have_sh():
        say("sh is not on PATH, so scripts/hermes.sh was not started.")
        return 1
    rest = safe_extras(extra, "agent argument")
    if rest is None:
        return 2
    try:
        proc = subprocess.run(
            ["sh", os.path.join(ROOT, "scripts", "hermes.sh"), *rest],
            cwd=ROOT,
        )
    except OSError as exc:
        say("cannot run hermes.sh: %s" % exc)
        return 1
    return proc.returncode


def agents_stop(apply, _extra):
    if not apply:
        return not_applied(
            "agents", "stop",
            "Does not stop model servers. A foreground hermes session is not a recorded pid.",
        )
    header("agents", "stop")
    say("agents stop does not stop model servers")
    return stop_recorded("agents")


# --- MCP --------------------------------------------------------------------

def mcp_names(doc):
    found = []
    for agent, spec in section(doc, "agents").items():
        if not isinstance(spec, dict):
            continue
        mcp = spec.get("mcp") or {}
        if isinstance(mcp, dict):
            for name in mcp:
                if isinstance(name, str):
                    found.append("%s.%s" % (agent, name))
    return found


def mcp_list(_apply, _extra):
    header("mcp", "list")
    doc = load_graph()
    if doc is None:
        return 1
    found = mcp_names(doc)
    say("count: %d declared under agents.*.mcp" % len(found))
    for name in found:
        say("  %s" % name)
    if not found:
        say("  (none in this graph)")
    say("example (not running): agent-reach via python3 scripts/agent_reach.py mcp-example")
    say("shape: docs/hermes-mcp.md")
    return 0


def mcp_status(_apply, _extra):
    code = mcp_list(False, [])
    listener_notice()
    say("MCP entries are stdio children of an agent, or URLs the agent opens. This command does not connect.")
    return code


def mcp_install(apply, _extra):
    if apply:
        header("mcp", "install")
        say("Refusing to install a listener.")
        listener_notice()
        say("Declare agents.<name>.mcp in graph.yaml (env_from names only). See docs/hermes-mcp.md.")
        return 0
    return not_applied(
        "mcp", "install",
        "Does not download or bind. Declare servers in graph.yaml; secrets stay env refs.",
    )


def mcp_start(apply, _extra):
    header("mcp", "start")
    say("Refusing to start a network listener.")
    listener_notice()
    say("Start the agent instead: python3 scripts/home_catalog.py agents start --apply")
    return 0


def mcp_stop(_apply, _extra):
    header("mcp", "stop")
    say("No MCP listener was started by the home menu.")
    say("nothing to stop")
    return 0


# --- tool sets --------------------------------------------------------------

def tools_list(_apply, _extra):
    header("tools", "list")
    ids = catalog_skills()
    say("count: %d in skills/catalog.json" % len(ids))
    for sid in ids:
        say("  %s" % sid)
    say("CLI: python3 scripts/skills.py list")
    return 0


def tools_status(_apply, _extra):
    header("tools", "status")
    ids = catalog_skills()
    say("catalog: %d" % len(ids))
    doc = load_graph()
    if doc is None:
        return 1
    for name, spec in section(doc, "agents").items():
        n = 0
        if isinstance(spec, dict) and isinstance(spec.get("skills"), list):
            n = len(spec["skills"])
        say("  agent %s skills=%d" % (name, n))
    say("CLI: python3 scripts/skills.py validate")
    return 0


def tools_install(apply, extra):
    if not apply:
        return not_applied(
            "tools", "install",
            "Vendors one catalog skill: python3 scripts/skills.py vendor SKILL.",
        )
    if not extra:
        header("tools", "install")
        say("Need a skill id: --apply SKILL")
        return 2
    skill = plain_arg(extra[0], "skill")
    rest = safe_extras(extra[1:], "skill argument")
    if skill is None or rest is None:
        return 2
    header("tools", "install")
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "skills.py"), "vendor", skill, *rest],
        cwd=ROOT,
    )
    return proc.returncode


def tools_start(apply, _extra):
    header("tools", "start")
    say("Tool sets are files an agent loads. They are not a process.")
    say("Start an agent: python3 scripts/home_catalog.py agents start --apply")
    listener_notice()
    return 0


def tools_stop(_apply, _extra):
    header("tools", "stop")
    say("Tool sets are not a process.")
    say("nothing to stop")
    return 0


# --- app store --------------------------------------------------------------

def app_rows():
    have = menu_names()
    return [(name, blurb) for name, blurb in APP_ITEMS if name in have]


def apps_list(_apply, _extra):
    header("apps", "list")
    rows = app_rows()
    say("count: %d local apps (by menu id)" % len(rows))
    for name, blurb in rows:
        say("  %s  %s" % (name, blurb))
    path = cache_file()
    if os.path.isfile(path):
        say("public-search cache: %s" % path)
    else:
        say("public-search cache: absent (%s)" % path)
    say("No network on list. Issue #397/#412 is the cached GitHub search.")
    return 0


def apps_status(_apply, _extra):
    header("apps", "status")
    say("local apps: %d" % len(app_rows()))
    path = cache_file()
    if os.path.isfile(path):
        say("cache bytes: %d" % os.path.getsize(path))
    else:
        say("cache: absent")
    listener_notice()
    return 0


def apps_install(apply, _extra):
    header("apps", "install")
    say("The app store does not download repositories or issues.")
    say("Run a local app with: ./familia-menu.sh --run KEY")
    listener_notice()
    return 0


def apps_start(apply, _extra):
    header("apps", "start")
    say("Refusing to start a listener for the app store.")
    listener_notice()
    say("Open one app from: python3 scripts/home_catalog.py apps list")
    return 0


def apps_stop(_apply, _extra):
    header("apps", "stop")
    say("The app store does not run a process.")
    say("nothing to stop")
    return 0


ACTIONS = {
    "models": {
        "list": models_list, "status": models_status, "install": models_install,
        "start": models_start, "stop": models_stop,
    },
    "harnesses": {
        "list": harnesses_list, "status": harnesses_status, "install": harnesses_install,
        "start": harnesses_start, "stop": harnesses_stop,
    },
    "agents": {
        "list": agents_list, "status": agents_status, "install": agents_install,
        "start": agents_start, "stop": agents_stop,
    },
    "mcp": {
        "list": mcp_list, "status": mcp_status, "install": mcp_install,
        "start": mcp_start, "stop": mcp_stop,
    },
    "tools": {
        "list": tools_list, "status": tools_status, "install": tools_install,
        "start": tools_start, "stop": tools_stop,
    },
    "apps": {
        "list": apps_list, "status": apps_status, "install": apps_install,
        "start": apps_start, "stop": apps_stop,
    },
}


def print_home():
    say("familia home - six equal items:")
    for i, title in enumerate(TITLES, 1):
        say("  %d) %-12s %s" % (i, title, VERBS_TEXT))
    say("  q) Quit")
    say("Legacy menu (fallback; reaches every item above): ./familia --legacy-menu")
    say("Legacy goals still on that menu:")
    for goal in LEGACY_GOALS:
        say("  %s" % goal)


def usage():
    return __doc__.strip()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        say(usage())
        return 0
    if argv[0] == "--list-home":
        print_home()
        return 0
    if argv[0] == "--titles":
        for title in TITLES:
            say(title)
        return 0
    if argv[0] == "--verbs":
        for verb in VERBS:
            say(verb)
        return 0
    if len(argv) < 2 or argv[0] not in AREA_OF or argv[1] not in VERBS:
        say(usage())
        return 2
    apply = False
    extra = []
    for arg in argv[2:]:
        if arg == "--apply":
            apply = True
        elif arg in ("-h", "--help"):
            say(usage())
            return 0
        else:
            extra.append(arg)
    if apply:
        lock = _ApplyLock(argv[0])
        try:
            lock.__enter__()
        except OSError as exc:
            say("apply lock failed (%s); nothing started" % exc)
            return 1
        try:
            return ACTIONS[argv[0]][argv[1]](apply, extra)
        finally:
            lock.__exit__(None, None, None)
    return ACTIONS[argv[0]][argv[1]](apply, extra)


if __name__ == "__main__":
    sys.exit(main())
