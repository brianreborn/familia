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
Model start --apply delegates to sh start.sh, which requires the instance
API key. MCP and the app store never open a listener.

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
APP_KEYS = (
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
API_KEY = (
    "Network listeners need an API key. This command does not bind a port."
)


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


def _runtime():
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
        if fcntl is None:
            return self
        try:
            import runtime_dir
            self.fd = runtime_dir.open_lock(os.path.join(_runtime(), "home-apply-%s.lock" % self.name))
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except OSError as exc:
            say("apply lock %s: %s" % (self.name, exc))
        return self

    def __exit__(self, *_a):
        if self.fd is None or fcntl is None:
            return False
        try:
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
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def save_record(kind, pid, port, cmdline):
    doc = {
        "pid": int(pid),
        "port": int(port),
        "starttime": _starttime(pid),
        "cmdline": (cmdline or "")[:240],
        "kind": kind,
    }
    path = _state_path(kind)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="ascii") as fh:
        fh.write(json.dumps(doc))
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


def same_process(rec):
    """True only when pid is alive, starttime matches, and cmdline still matches.

    A reused pid fails the starttime check, so stop will not signal it.
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
    if started and _starttime(pid) != started:
        return False
    stored = rec.get("cmdline") or ""
    current = _cmdline(pid)
    if stored and stored[:80] not in current and not current.startswith(stored[:80]):
        return False
    return True


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


def stop_recorded(kind):
    """Signal the recorded process and its children. Never a different pid."""
    rec = load_record(kind)
    if not same_process(rec):
        say("nothing to stop")
        if rec:
            say("recorded pid %s port %s is not the process this menu started" % (
                rec.get("pid"), rec.get("port")))
        else:
            say("no %s process recorded by this menu" % kind)
        return 0
    pid = int(rec["pid"])
    victims = [pid] + descendants(pid)
    for target in victims:
        try:
            os.kill(target, signal.SIGTERM)
            say("signaled pid %s" % target)
        except OSError as exc:
            say("pid %s: %s" % (target, exc))
    try:
        os.remove(_state_path(kind))
    except OSError:
        pass
    say("stopped %s pid %s port %s" % (kind, pid, rec.get("port")))
    return 0


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


def menu_keys():
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


def not_applied(area, verb, detail):
    header(area, verb)
    say(detail)
    say("Not applied. Re-run with --apply to do it.")
    say(API_KEY)
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
    keys = list(section(doc, "models"))
    say("count: %d in %s" % (len(keys), graph_path()))
    for key in keys:
        say("  %s" % key)
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
    say(API_KEY)
    return 0


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
    header("models", "install")
    if _windows():
        say("running: python scripts\\add_model.py --fetch %s" % extra[0])
        return _run_checked([sys.executable, os.path.join(ROOT, "scripts", "add_model.py"),
                             "--fetch", extra[0], *extra[1:]])
    say("running: scripts/add-model.sh --fetch %s" % extra[0])
    return _run_checked(["sh", os.path.join(ROOT, "scripts", "add-model.sh"),
                         "--fetch", extra[0], *extra[1:]])


def _remember_started(blob, kind):
    match = re.search(r"PID:\s*(\d+)", blob)
    if not match:
        say("no PID in launcher output; nothing recorded")
        return
    pid = int(match.group(1))
    cmd = _cmdline(pid) or kind
    save_record(kind, pid, _port(), cmd)
    say("recorded pid %s port %s" % (pid, _port()))


def models_start(apply, extra):
    if not apply:
        return not_applied(
            "models", "start",
            "Delegates to sh start.sh with DETACH_MODE=nohup (Windows: scripts\\windows\\start.bat). "
            "The launcher requires the instance API key. This menu records that pid and port.",
        )
    if os.environ.get("FAMILIA_HOME_TEST_HOLD") == "1":
        header("models", "start")
        say("holding for test")
        import time
        time.sleep(30)
        return 0
    header("models", "start")
    say("start requires the instance API key (scripts/familia_auth.py).")
    if _windows():
        bat = os.path.join(ROOT, "scripts", "windows", "start.bat")
        say("running: scripts\\windows\\start.bat")
        if not os.path.isfile(bat):
            say("start.bat is missing")
            return 1
        try:
            proc = subprocess.run(["cmd", "/c", bat, *extra], cwd=ROOT, capture_output=True, text=True)
        except OSError as exc:
            say("cannot run start.bat: %s" % exc)
            return 1
        say(proc.stdout or "")
        say(proc.stderr or "")
        if proc.returncode == 0:
            _remember_started((proc.stdout or "") + (proc.stderr or ""), "models")
        return proc.returncode
    say("running: DETACH_MODE=nohup sh start.sh")
    env = dict(os.environ)
    env["DETACH_MODE"] = "nohup"
    if not _have_sh():
        say("sh is not on PATH. On Windows run scripts\\windows\\start.bat.")
        return 1
    try:
        proc = subprocess.run(
            ["sh", os.path.join(ROOT, "start.sh"), *extra],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
    except OSError as exc:
        say("cannot run start.sh: %s" % exc)
        return 1
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    say(blob)
    if proc.returncode == 0:
        _remember_started(blob, "models")
    return proc.returncode


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
    for key, spec in section(doc, "harnesses").items():
        kind = spec.get("kind") if isinstance(spec, dict) else ""
        rows.append((key, "harnesses", str(kind or "")))
    for key, spec in section(doc, "self_improve").items():
        mode = ""
        if isinstance(spec, dict):
            mode = str(spec.get("mode") or "")
        rows.append((key, "self_improve", mode))
    return rows


def harnesses_list(_apply, _extra):
    header("harnesses", "list")
    doc = load_graph()
    if doc is None:
        return 1
    rows = harness_rows(doc)
    say("count: %d" % len(rows))
    for key, where, detail in rows:
        say("  %s  %s  %s" % (key, where, detail))
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
    header("harnesses", "start")
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "harness2.py"),
         "set", "--agent", extra[0], "--mode", "propose", *extra[1:]],
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
    header("harnesses", "stop")
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "harness2.py"),
         "set", "--agent", extra[0], "--mode", "off", *extra[1:]],
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
    for key, spec in rows.items():
        kind = host = ""
        if isinstance(spec, dict):
            kind = str(spec.get("kind") or "")
            host = str(spec.get("host") or "")
        say("  %s  kind=%s  host=%s" % (key, kind, host))
    say("CLI: familia hermes")
    return 0


def agents_status(_apply, _extra):
    header("agents", "status")
    doc = load_graph()
    if doc is None:
        return 1
    for key, spec in section(doc, "agents").items():
        skills = []
        if isinstance(spec, dict) and isinstance(spec.get("skills"), list):
            skills = [str(s) for s in spec["skills"]]
        say("  %s  skills=%d" % (key, len(skills)))
    say(API_KEY)
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
            "Runs scripts/hermes.sh (license review first; the server it uses keeps the instance API key).",
        )
    header("agents", "start")
    say(API_KEY)
    if not _have_sh():
        say("sh is not on PATH, so scripts/hermes.sh was not started.")
        return 1
    try:
        proc = subprocess.run(
            ["sh", os.path.join(ROOT, "scripts", "hermes.sh"), *extra],
            cwd=ROOT, capture_output=True, text=True,
        )
    except OSError as exc:
        say("cannot run hermes.sh: %s" % exc)
        return 1
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    say(blob)
    return proc.returncode


def agents_stop(apply, _extra):
    if not apply:
        return not_applied(
            "agents", "stop",
            "Stops only an agent process this menu recorded. It does not stop model servers.",
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
    say(API_KEY)
    say("MCP entries are stdio children of an agent, or URLs the agent opens. This command does not connect.")
    return code


def mcp_install(apply, _extra):
    if apply:
        header("mcp", "install")
        say("Refusing to install a listener.")
        say(API_KEY)
        say("Declare agents.<name>.mcp in graph.yaml (env_from names only). See docs/hermes-mcp.md.")
        return 0
    return not_applied(
        "mcp", "install",
        "Does not download or bind. Declare servers in graph.yaml; secrets stay env refs.",
    )


def mcp_start(apply, _extra):
    header("mcp", "start")
    say("Refusing to start a network listener.")
    say(API_KEY)
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
    for key, spec in section(doc, "agents").items():
        n = 0
        if isinstance(spec, dict) and isinstance(spec.get("skills"), list):
            n = len(spec["skills"])
        say("  agent %s skills=%d" % (key, n))
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
    header("tools", "install")
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "skills.py"), "vendor", extra[0], *extra[1:]],
        cwd=ROOT,
    )
    return proc.returncode


def tools_start(apply, _extra):
    header("tools", "start")
    say("Tool sets are files an agent loads. They are not a process.")
    say("Start an agent: python3 scripts/home_catalog.py agents start --apply")
    say(API_KEY)
    return 0


def tools_stop(_apply, _extra):
    header("tools", "stop")
    say("Tool sets are not a process.")
    say("nothing to stop")
    return 0


# --- app store --------------------------------------------------------------

def app_rows():
    have = menu_keys()
    return [(key, blurb) for key, blurb in APP_KEYS if key in have]


def apps_list(_apply, _extra):
    header("apps", "list")
    rows = app_rows()
    say("count: %d local apps (by menu key)" % len(rows))
    for key, blurb in rows:
        say("  %s  %s" % (key, blurb))
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
    say(API_KEY)
    return 0


def apps_install(apply, _extra):
    header("apps", "install")
    say("The app store does not download repositories or issues.")
    say("Run a local app with: ./familia-menu.sh --run KEY")
    say(API_KEY)
    return 0


def apps_start(apply, _extra):
    header("apps", "start")
    say("Refusing to start a listener for the app store.")
    say(API_KEY)
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
        with _ApplyLock(argv[0]):
            return ACTIONS[argv[0]][argv[1]](apply, extra)
    return ACTIONS[argv[0]][argv[1]](apply, extra)


if __name__ == "__main__":
    sys.exit(main())
