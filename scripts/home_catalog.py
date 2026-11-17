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
import subprocess
import sys

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
    say("screen familia-server: %s" % screen_session())
    log_lines()
    say(API_KEY)
    return 0


def models_install(apply, extra):
    if not apply:
        return not_applied(
            "models", "install",
            "Installs one Hugging Face repo via scripts/add-model.sh --fetch REPO.",
        )
    if not extra:
        header("models", "install")
        say("Need a repo: --apply ORG/NAME")
        return 2
    header("models", "install")
    say("running: scripts/add-model.sh --fetch %s" % extra[0])
    proc = subprocess.run(
        ["sh", os.path.join(ROOT, "scripts", "add-model.sh"), "--fetch", extra[0], *extra[1:]],
        cwd=ROOT,
    )
    return proc.returncode


def models_start(apply, extra):
    if not apply:
        return not_applied(
            "models", "start",
            "Delegates to sh start.sh with DETACH_MODE=nohup. start.sh requires the instance API key.",
        )
    header("models", "start")
    say("running: DETACH_MODE=nohup sh start.sh")
    say("start.sh requires the instance API key (scripts/familia_auth.py).")
    env = dict(os.environ)
    env["DETACH_MODE"] = "nohup"
    proc = subprocess.run(["sh", os.path.join(ROOT, "start.sh"), *extra], cwd=ROOT, env=env)
    return proc.returncode


def models_stop(apply, _extra):
    if not apply:
        return not_applied(
            "models", "stop",
            "Quits the screen session named familia-server when that session exists.",
        )
    header("models", "stop")
    state = screen_session()
    say("screen familia-server: %s" % state)
    if state != "present":
        say("nothing to stop")
        return 0
    proc = subprocess.run(["screen", "-S", "familia-server", "-X", "quit"], cwd=ROOT)
    if proc.returncode != 0:
        say("screen quit failed")
        return proc.returncode
    say("quit familia-server")
    return 0


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
    proc = subprocess.run(
        ["sh", os.path.join(ROOT, "scripts", "hermes.sh"), "--render-only", *extra],
        cwd=ROOT,
    )
    return proc.returncode


def agents_start(apply, extra):
    if not apply:
        return not_applied(
            "agents", "start",
            "Runs scripts/hermes.sh (license review first; the server it uses keeps the instance API key).",
        )
    header("agents", "start")
    say(API_KEY)
    proc = subprocess.run(["sh", os.path.join(ROOT, "scripts", "hermes.sh"), *extra], cwd=ROOT)
    return proc.returncode


def agents_stop(apply, _extra):
    if not apply:
        return not_applied(
            "agents", "stop",
            "Agents are not a standing listener. Stop is a no-op unless a familia-server screen session is up.",
        )
    return models_stop(True, [])


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
    return ACTIONS[argv[0]][argv[1]](apply, extra)


if __name__ == "__main__":
    sys.exit(main())
