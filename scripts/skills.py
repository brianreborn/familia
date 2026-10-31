#!/usr/bin/env python3
"""skills.py: pick the bundled skills your agents use. green-zkillz is where they live.

Skills are folders of instructions (a SKILL.md, sometimes with scripts) that make
a small local model much better at one job. skills/catalog.json lists them, each
with its license, a pinned commit and a status:
  bundled          already in green-zkillz (brianreborn/green-agentz skills/)
  available        reviewed source, not vendored into green-zkillz yet
  vendored         copied into green-zkillz with attribution, pinned
  license-blocked  cannot be enabled until the license is cleared
Enabling writes `skills: [ids]` under the agent in graph.yaml (comments kept)
after you accept the licenses (scripts/licenses.py).

Usage:
  scripts/skills.py list [--json]                    every skill, its license and status
  scripts/skills.py show ID                          full entry
  scripts/skills.py enable ID... [--agent NAME] [--dry-run] [--yes]
  scripts/skills.py disable ID... [--agent NAME] [--dry-run]
  scripts/skills.py menu [--agent NAME]              toggle skills on a terminal
  scripts/skills.py vendor ID --dry-run              show the plan to vendor ID into green-zkillz
  scripts/skills.py paths [--agent NAME]             local folders of the enabled skills
  scripts/skills.py validate                         check the catalog and graph.yaml skills
Example:
  scripts/skills.py enable green-probe --agent hermes --dry-run
--agent defaults to hermes. --yes accepts the license review without a prompt.
Exit codes: 0 ok; 1 refused or invalid; 2 usage error or no terminal.
Docs: docs/skills.md, docs/licenses.md.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import familia_yaml  # noqa: E402

CATALOG = os.environ.get("FAMILIA_SKILLS_CATALOG") or os.path.join(ROOT, "skills", "catalog.json")
STATUSES = ("bundled", "available", "vendored", "license-blocked")
REQUIRED = ("id", "name", "description", "home", "repo", "commit", "license", "attribution", "path",
            "applies_to", "adds_tools", "status")
OPTIONAL = ("license_file", "notes", "vendor_plan", "survey", "blocked_reason", "parts")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MOVE_PLAN_ISSUE = os.environ.get("FAMILIA_ZKILLZ_ISSUE", "")


def die(msg, code=1):
    sys.stderr.write(f"skills: {msg}\n")
    sys.exit(code)


def load_catalog(path=None):
    path = path or CATALOG
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"version": 1, "homes": {}, "skills": []}
    except ValueError as e:
        die(f"{path} is not valid JSON ({e}). Fix the file or restore it with git checkout skills/catalog.json")


def validate_catalog(cat):
    errs = []
    if not isinstance(cat, dict) or cat.get("version") != 1:
        return ["catalog: expected a JSON object with version: 1"]
    seen = set()
    for n, s in enumerate(cat.get("skills") or []):
        w = f"skills[{n}]"
        if not isinstance(s, dict):
            errs.append(f"{w}: expected an object"); continue
        sid = s.get("id")
        w = f"skill {sid or n}"
        for k in REQUIRED:
            if k not in s:
                errs.append(f"{w}: missing required field {k!r}")
        for k in s:
            if k not in REQUIRED + OPTIONAL:
                errs.append(f"{w}: unknown field {k!r}")
        if not isinstance(sid, str) or not ID_RE.match(sid):
            errs.append(f"{w}: id must be lowercase letters, digits, '.', '_' or '-'")
        elif sid in seen:
            errs.append(f"{w}: duplicate id")
        seen.add(sid)
        if s.get("status") not in STATUSES:
            errs.append(f"{w}: status {s.get('status')!r} not one of {list(STATUSES)}")
        if not (isinstance(s.get("commit"), str) and SHA_RE.match(s["commit"])):
            errs.append(f"{w}: commit must be a full 40-character git SHA (pin it)")
        if not (isinstance(s.get("repo"), str) and s["repo"].startswith("https://")):
            errs.append(f"{w}: repo must be an https:// URL")
        if not isinstance(s.get("adds_tools"), bool):
            errs.append(f"{w}: adds_tools must be true or false (true if it ships scripts, MCP servers or tool definitions)")
        at = s.get("applies_to")
        if not (isinstance(at, list) and at and all(isinstance(x, str) and x for x in at)):
            errs.append(f"{w}: applies_to must be a non-empty list of agent names")
        for k in ("license", "attribution", "name", "description", "path"):
            if k in s and not (isinstance(s[k], str) and s[k].strip()):
                errs.append(f"{w}: {k} must be a non-empty string")
        if s.get("status") == "license-blocked" and not s.get("blocked_reason"):
            errs.append(f"{w}: license-blocked needs blocked_reason (say what must be cleared)")
        if s.get("status") == "bundled" and s.get("home") != "green-zkillz":
            errs.append(f"{w}: bundled skills live in green-zkillz (home: green-zkillz)")
        if s.get("home") and s["home"] not in (cat.get("homes") or {}):
            errs.append(f"{w}: home {s['home']!r} is not in homes")
    return errs


def check_graph_skills(g, cat=None):
    """Errors for skills: lists in graph agents/pentests. Called from graph_types.py too."""
    cat = cat if cat is not None else load_catalog()
    by_id = {s.get("id"): s for s in cat.get("skills") or [] if isinstance(s, dict)}
    errs = []
    for sec in ("agents", "pentests"):
        for name, a in (g.get(sec) or {}).items():
            if not isinstance(a, dict) or "skills" not in a:
                continue
            lst = a.get("skills")
            w = f"{sec}.{name}.skills"
            if not isinstance(lst, list) or not all(isinstance(x, str) for x in lst):
                errs.append(f"{w}: expected a list of skill ids, e.g. [green-probe]"); continue
            if len(set(lst)) != len(lst):
                errs.append(f"{w}: lists a skill twice")
            agent = name if sec == "agents" else a.get("agent")
            for sid in lst:
                s = by_id.get(sid)
                if s is None:
                    errs.append(f"{w}: {sid!r} is not in skills/catalog.json (see scripts/skills.py list)"); continue
                if s.get("status") == "license-blocked":
                    errs.append(f"{w}: {sid!r} is license-blocked ({s.get('blocked_reason', 'license not cleared')})")
                if agent not in (s.get("applies_to") or []):
                    errs.append(f"{w}: {sid!r} does not apply to agent {agent!r} (applies_to: {s.get('applies_to')})")
                if sec == "pentests" and s.get("adds_tools") is not False:
                    errs.append(f"{w}: {sid!r} adds tools; pentest roles never get tool-adding skills "
                                "(tools stay disabled: tools.allow is empty and launch_test_only is true)")
    return errs


def graph_path():
    import config_paths
    return config_paths.graph_path()  # DUP-02


def load_graph():
    p = graph_path()
    if not os.path.isfile(p):
        die(f"graph not found: {p}. Run from a familia checkout, or set FAMILIA_GRAPH.", 2)
    return familia_yaml.load(p)


def enabled_for(g, agent):
    for sec in ("agents", "pentests"):
        if agent in (g.get(sec) or {}):
            return sec, list((g[sec][agent] or {}).get("skills") or [])
    die(f"no agent or pentest named {agent!r} in graph.yaml. Agents: {sorted((g.get('agents') or {}))}", 1)


def home_dir(cat, s):
    h = (cat.get("homes") or {}).get(s.get("home")) or {}
    for base in (os.path.join(ROOT, h.get("checkout", "")), os.path.join(ROOT, "..", h.get("checkout", ""))):
        if h.get("checkout") and os.path.isdir(base):
            return os.path.realpath(base), h
    return None, h


def skill_dir(cat, s):
    base, h = home_dir(cat, s)
    if not base:
        return None
    if s.get("status") == "bundled":
        return os.path.join(base, s["path"])
    if s.get("status") == "vendored":
        return os.path.join(base, h.get("skills_dir", "skills"), s["id"])
    return None


def fmt_row(n, s, on):
    mark = "[x]" if on else "[ ]"
    if s.get("status") == "license-blocked":
        mark = "[-]"
    tools = " +tools" if s.get("adds_tools") else ""
    return f"{n:>3} {mark} {s['id']:<24} {s['status']:<16} {s['license'][:34]:<34}{tools}"


def cmd_list(cat, g, agent, as_json):
    on = set(enabled_for(g, agent)[1]) if g is not None else set()
    if as_json:
        print(json.dumps([dict(s, enabled=s["id"] in on) for s in cat.get("skills") or []], indent=2)); return 0
    print(f"Bundled skills (home: green-zkillz). [x] enabled for {agent}, [ ] off, [-] license-blocked.")
    print(f"{'#':>3} {'':3} {'id':<24} {'status':<16} {'license':<34}")
    for n, s in enumerate(cat.get("skills") or [], 1):
        print(fmt_row(n, s, s["id"] in on))
    print("\n+tools = ships scripts the agent can run. Pentest roles never get these.")
    print("Turn one on:  scripts/skills.py enable ID --agent", agent)
    return 0


def cmd_show(cat, sid):
    s = find(cat, sid)
    for k in REQUIRED + OPTIONAL:
        if k in s:
            v = s[k]
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            print(f"{k:>14}: {v}")
    d = skill_dir(cat, s)
    print(f"{'local files':>14}: {d if d and os.path.isdir(d) else 'not on this machine (run sh scripts/configure.sh)' if s['status'] in ('bundled', 'vendored') else 'not vendored yet'}")
    return 0


def find(cat, sid):
    for s in cat.get("skills") or []:
        if s.get("id") == sid:
            return s
    die(f"no skill {sid!r}. See: scripts/skills.py list", 1)


def license_gate(sids, yes):
    import licenses
    items, digest = licenses.selection(graph_path(), sids)
    if licenses.accepted(digest, items):
        return 0
    unknown_ok = licenses.env_yes("FAMILIA_ACCEPT_UNKNOWN_LICENSES")
    return licenses.do_review(items, digest, yes or licenses.env_yes("FAMILIA_ACCEPT_LICENSES"), unknown_ok, False)


def owner_of(g, sec, agent):
    """The agent whose skills apply: the agent itself, or a pentest role's agent."""
    return ((g.get("pentests") or {}).get(agent) or {}).get("agent") if sec == "pentests" else agent


def refusal(s, sec, owner):
    """Why skill s cannot be switched on for owner (sec is 'agents' or 'pentests'), or None.
    The one rule set for the terminal skills menu (scripts/skills.py)."""
    if s["status"] == "license-blocked":
        return f"{s['id']} is license-blocked and can't be enabled: {s.get('blocked_reason')}"
    if s["status"] == "available":
        return (f"{s['id']} isn't vendored into green-zkillz yet ({s['license']}), so there are no files to load. "
                f"Plan: scripts/skills.py vendor {s['id']} --dry-run")
    if owner not in (s.get("applies_to") or []):
        return f"{s['id']} is for {', '.join(s.get('applies_to') or [])}, not {owner}."
    if sec == "pentests" and s["adds_tools"] is not False:
        return f"{s['id']} adds tools; pentest roles never get those (launch-test only)."
    return None


def graph_text_with(sec, agent, new):
    """graph.yaml text with sec.agent.skills set to new (comments kept). ValueError lists refusals."""
    with open(graph_path(), encoding="utf-8") as fh:
        text = fh.read()
    out = familia_yaml.set_node_list(text, sec, agent, "skills", new)
    errs = check_graph_skills(familia_yaml.loads(out))
    if errs:
        raise ValueError("refusing to write graph.yaml:\n  " + "\n  ".join(errs))
    return out


def write_skills(sec, agent, new):
    p = graph_path()
    try:
        out = graph_text_with(sec, agent, new)
    except ValueError as e:
        die(str(e))
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(out)
    os.replace(tmp, p)


def cmd_enable(cat, g, sids, agent, dry, yes, disable=False):
    sec, cur = enabled_for(g, agent)
    new = list(cur)
    for sid in sids:
        s = find(cat, sid)
        if disable:
            if sid in new:
                new.remove(sid)
            continue
        if s["status"] == "license-blocked":
            die(f"{sid} is license-blocked and can't be enabled.\n  Why: {s.get('blocked_reason')}\n"
                f"  Next: clear the license (see {s.get('survey', 'skills/catalog.json')}), then set its status in skills/catalog.json.")
        if s["status"] == "available":
            die(f"{sid} is not vendored into green-zkillz yet, so there are no files to load.\n"
                f"  Its license is {s['license']}. See the plan: scripts/skills.py vendor {sid} --dry-run")
        owner = owner_of(g, sec, agent)
        if owner not in s["applies_to"]:
            die(f"{sid} is for {s['applies_to']}, not {owner!r}. Pick one of those with --agent.")
        if sec == "pentests" and s["adds_tools"]:
            die(f"{sid} adds tools, and pentest roles never get tool-adding skills (launch-test only).")
        if sid not in new:
            new.append(sid)
    if new == cur:
        print(f"skills: nothing to change for {agent} (enabled: {cur or 'none'})"); return 0
    errs = check_graph_skills({sec: {agent: dict((g.get(sec) or {}).get(agent) or {}, skills=new)},
                               **({"agents": g.get("agents")} if sec == "pentests" else {})})
    if errs:
        die("\n  ".join(["refused:"] + errs))
    line = f"{sec}.{agent}.skills: {cur} -> {new}"
    if dry:
        print(f"[dry-run] would set {line} in graph.yaml (nothing written)")
        if not disable:
            print(f"[dry-run] licenses you would accept: " +
                  ", ".join(f"{find(cat, x)['id']}={find(cat, x)['license']}" for x in sids))
        return 0
    if not disable:
        added = [x for x in new if x not in cur]
        rc = license_gate(added, yes)
        if rc:
            sys.stderr.write("skills: licenses not accepted; graph.yaml was not changed.\n"); return rc
    write_skills(sec, agent, new)
    print(f"skills: set {line}")
    print("Next: restart the agent (scripts/hermes.sh) so it loads the new skills.")
    return 0


def cmd_vendor(cat, sid, dry):
    s = find(cat, sid)
    if not dry:
        die("vendoring is not automated yet: license review is pending (familia #67) and the move plan into "
            "green-zkillz is still open. Use --dry-run to see the plan.", 2)
    _, h = home_dir(cat, s)
    if s["status"] == "bundled":
        print(f"{sid} is already bundled in green-zkillz ({h.get('repo')} @ {h.get('commit', '')[:12]}, {s['path']})."); return 0
    if s["status"] == "license-blocked":
        print(f"{sid} is license-blocked; no vendor plan until it's cleared: {s.get('blocked_reason')}"); return 1
    dest = f"{h.get('checkout', 'green-agentz')}/{h.get('skills_dir', 'skills')}/{sid}"
    print(f"[dry-run] vendor plan for {sid} (nothing is done):")
    print(f"  1. git clone {s['repo']} and check out {s['commit']}")
    print(f"  2. copy {s['path']} into green-zkillz at {dest}/")
    print(f"  3. keep {s.get('license_file', 'LICENSE')} and add ATTRIBUTION.md: {s['attribution']}")
    print(f"  4. commit to {h.get('repo')} and set status: vendored in skills/catalog.json; bump the green-agentz pin in pins.txt")
    print(f"  license: {s['license']}. Review pending: {s.get('survey', 'familia #67')}")
    return 0


def cmd_paths(cat, g, agent):
    _, cur = enabled_for(g, agent)
    rc = 0
    for sid in cur:
        s = find(cat, sid)
        d = skill_dir(cat, s)
        if d and os.path.isdir(d):
            print(d)
        else:
            sys.stderr.write(f"skills: {sid}: files not on this machine; run sh scripts/configure.sh\n"); rc = 1
    return rc


def ask(prompt):
    sys.stderr.write(prompt); sys.stderr.flush()
    line = sys.stdin.readline()
    return None if not line else line.strip()


def cmd_menu(cat, g, agent, yes):
    skills = cat.get("skills") or []
    sec, cur = enabled_for(g, agent)
    if not sys.stdin.isatty() and not os.environ.get("FAMILIA_MENU_PIPE"):
        cmd_list(cat, g, agent, False)
        sys.stderr.write("skills: no terminal, so no menu. Use: scripts/skills.py enable|disable ID --agent "
                         f"{agent}\n")
        return 2
    sel = list(cur)
    while True:
        print(f"\nBundled skills for {agent}  (green-zkillz is their home)")
        for n, s in enumerate(skills, 1):
            print(fmt_row(n, s, s["id"] in sel))
        print("  type a number to switch it on/off, i NUMBER for details, s to save, q to quit without saving")
        a = ask("skills> ")
        if a is None or a in ("q", "quit"):
            print("skills: nothing saved."); return 0
        if a in ("s", "save", "d", "done"):
            break
        info = a.startswith("i ")
        a = a[2:].strip() if info else a
        if not a.isdigit() or not 1 <= int(a) <= len(skills):
            print(f"  '{a}' is not a skill number (1-{len(skills)})."); continue
        s = skills[int(a) - 1]
        if info:
            cmd_show(cat, s["id"]); continue
        if s["id"] in sel:
            sel.remove(s["id"]); continue
        why = refusal(s, sec, owner_of(g, sec, agent))
        if why:
            print(f"  {why}"); continue
        sel.append(s["id"])
    off = [x for x in cur if x not in sel]
    on = [x for x in sel if x not in cur]
    if not on and not off:
        print("skills: no changes."); return 0
    if off:
        cmd_enable(cat, familia_yaml.load(graph_path()), off, agent, False, yes, disable=True)
    if on:
        return cmd_enable(cat, familia_yaml.load(graph_path()), on, agent, False, yes)
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip()); return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    agent, dry, yes, as_json, ids = "hermes", False, False, False, []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--agent" and i + 1 < len(rest): agent = rest[i + 1]; i += 1
        elif a.startswith("--agent="): agent = a.split("=", 1)[1]
        elif a in ("--dry-run", "-n"): dry = True
        elif a in ("--yes", "-y", "--accept-licenses"): yes = True
        elif a == "--json": as_json = True
        elif a in ("-h", "--help"): print(__doc__.strip()); return 0
        elif a.startswith("-"): die(f"unknown option {a!r}. Try: scripts/skills.py --help", 2)
        else: ids.append(a)
        i += 1
    cat = load_catalog()
    errs = validate_catalog(cat)
    if cmd == "validate":
        errs += check_graph_skills(load_graph(), cat)
        for e in errs:
            print(f"skills: {e}")
        print("skills: catalog and graph skills OK" if not errs else f"skills: {len(errs)} problem(s)")
        return 1 if errs else 0
    if errs:
        die("skills/catalog.json has problems:\n  " + "\n  ".join(errs) + "\n  Next: fix them, then run scripts/skills.py validate")
    if cmd == "list":
        return cmd_list(cat, load_graph(), agent, as_json)
    if cmd in ("show", "vendor") and len(ids) != 1:
        die(f"usage: scripts/skills.py {cmd} ID" + (" --dry-run" if cmd == "vendor" else ""), 2)
    if cmd == "show":
        return cmd_show(cat, ids[0])
    if cmd == "vendor":
        return cmd_vendor(cat, ids[0], dry)
    if cmd in ("enable", "disable"):
        if not ids:
            die(f"usage: scripts/skills.py {cmd} ID... [--agent NAME] [--dry-run]", 2)
        return cmd_enable(cat, load_graph(), ids, agent, dry, yes, disable=cmd == "disable")
    if cmd == "paths":
        return cmd_paths(cat, load_graph(), agent)
    if cmd == "menu":
        return cmd_menu(cat, load_graph(), agent, yes)
    die(f"unknown command {cmd!r}. Try: scripts/skills.py --help", 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
