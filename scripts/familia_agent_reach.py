#!/usr/bin/env python3
"""Agent-Reach reach tools: status, enable/disable for an agent, link into HERMES_HOME.

Agent-Reach (pins.txt → Panniantong/Agent-Reach, MIT, not vendored) is the reach
node: web / login-walled / video / Chinese-platform tools. Tools enter through
the existing approval gate (terminal / MCP); they are never pasted into
llama-server. See docs/agent-reach.md, DESIGN.md § Agent-Reach.

usage:
  scripts/agent_reach.py status [--agent NAME]
  scripts/agent_reach.py enable --agent NAME [--dry-run]
  scripts/agent_reach.py disable --agent NAME [--dry-run]
  scripts/agent_reach.py link --agent NAME [--home DIR] [--dry-run]
  scripts/agent_reach.py mcp-example
"""
import argparse
import json
import os
import re
import shlex
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import familia_yaml  # noqa: E402

PIN_NAME = "agent-reach"
REACH_KEY = "agent-reach"
DEFAULT_REPO = "Panniantong/Agent-Reach"
SKILL_REL = os.path.join("agent_reach", "skill")


def die(msg, code=1):
    print(f"agent-reach: {msg}", file=sys.stderr)
    sys.exit(code)


def graph_path():
    import config_paths
    return config_paths.graph_path()  # DUP-02


def load_graph(path=None):
    p = path or graph_path()
    g = familia_yaml.load(p) or {}
    g["_path"] = p
    return g


def pin_checkout(root=ROOT):
    for cand in (os.path.join(root, PIN_NAME), os.path.join(root, "..", PIN_NAME)):
        if os.path.isdir(os.path.join(cand, "agent_reach")):
            return os.path.realpath(cand)
    return None


def skill_dir(checkout=None):
    c = checkout or pin_checkout()
    if not c:
        return None
    d = os.path.join(c, SKILL_REL)
    return d if os.path.isdir(d) and os.path.isfile(os.path.join(d, "SKILL.md")) else None


def cli_on_path():
    return shutil.which("agent-reach")


def reaches_for(g, agent=None):
    out = []
    for name, r in (g.get("reaches") or {}).items():
        if not isinstance(r, dict):
            continue
        if agent is not None and agent not in (r.get("agents") or []):
            continue
        out.append((name, r))
    return out


def agents_with_reach(g, reach=REACH_KEY):
    r = (g.get("reaches") or {}).get(reach) or {}
    return list(r.get("agents") or [])


def validate_reach_entry(g, name, r, errs=None):
    errs = errs if errs is not None else []
    if not isinstance(r, dict):
        errs.append(f"reaches.{name}: must be a mapping")
        return errs
    if r.get("experimental") is not True:
        errs.append(f"reaches.{name}: experimental type; set 'experimental: true' to acknowledge")
    repo = r.get("repo")
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        errs.append(f"reaches.{name}: repo must look like owner/name, got {repo!r}")
    agents = r.get("agents")
    if not isinstance(agents, list) or not agents:
        errs.append(f"reaches.{name}: agents must be a non-empty list")
    else:
        known = set((g.get("agents") or {}) or {})
        for a in agents:
            if a not in known:
                errs.append(f"reaches.{name}: agent {a!r} not in agents:")
    return errs


def cmd_status(g, agent):
    checkout = pin_checkout()
    skill = skill_dir(checkout)
    which = cli_on_path()
    print(f"pin: {PIN_NAME} → {DEFAULT_REPO} (pins.txt; not vendored)")
    print(f"checkout: {checkout or 'missing (run: python3 scripts/sync_pins.py)'}")
    print(f"skill: {skill or 'missing'}")
    print(f"CLI on PATH: {which or 'no (link writes a HERMES_HOME/bin wrapper; or uv tool install from the pin)'}")
    if not (g.get("reaches") or {}):
        print("graph: no reaches: declared (enable with: scripts/agent_reach.py enable --agent NAME)")
        return 0
    print("graph reaches:")
    for name, r in (g.get("reaches") or {}).items():
        agents = ",".join(r.get("agents") or []) or "-"
        mark = "  ← this agent" if agent and agent in (r.get("agents") or []) else ""
        print(f"  {name}: repo={r.get('repo')} experimental={r.get('experimental')} agents=[{agents}]{mark}")
    if agent and not reaches_for(g, agent):
        print(f"agent {agent!r}: not listed under any reaches.*.agents")
    return 0


def _block(lines, section, name=None):
    si = next((i for i, l in enumerate(lines) if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", l)), None)
    if si is None:
        return None
    se = next((i for i in range(si + 1, len(lines))
               if lines[i] and not lines[i][0].isspace() and not lines[i].startswith("#")), len(lines))
    if name is None:
        return si, se
    ni = next((i for i in range(si + 1, se)
               if re.match(rf"^(\s+){re.escape(name)}:\s*(#.*)?$", lines[i])), None)
    if ni is None:
        return None
    ind = len(lines[ni]) - len(lines[ni].lstrip(" "))
    ne = next((i for i in range(ni + 1, se)
               if lines[i].strip() and not lines[i].lstrip().startswith("#")
               and len(lines[i]) - len(lines[i].lstrip(" ")) <= ind), se)
    return ni, ne


def set_agents_list(text, reach, agents):
    rendered = "[" + ", ".join(agents) + "]"
    lines = text.split("\n")
    b = _block(lines, "reaches", reach)
    if b is None:
        body = [
            "experimental: true",
            f"repo: {DEFAULT_REPO}",
            f"agents: {rendered}",
        ]
        sec = _block(lines, "reaches")
        entry = [f"  {reach}:"] + [f"    {l}" for l in body]
        if sec is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", "reaches:  # experimental Agent-Reach tool bundle (docs/agent-reach.md)",
                      "  # Tools enter through the approval gate; never pasted into llama-server."] + entry + [""]
        else:
            last = sec[1]
            while last > sec[0] + 1 and not lines[last - 1].strip():
                last -= 1
            lines[last:last] = entry
        return "\n".join(lines)
    for i in range(b[0] + 1, b[1]):
        m = re.match(r"^(\s+)agents:(\s*)([^#]*?)(\s*)(#.*)?$", lines[i])
        if m:
            old_w = len(m.group(3)) + len(m.group(4))
            pad = " " * max(2, old_w - len(rendered)) if m.group(5) else ""
            lines[i] = f"{m.group(1)}agents:{m.group(2) or ' '}{rendered}{pad}{m.group(5) or ''}"
            return "\n".join(lines)
    ind = len(lines[b[0]]) - len(lines[b[0]].lstrip(" ")) + 2
    last = b[1]
    while last > b[0] + 1 and not lines[last - 1].strip():
        last -= 1
    lines.insert(last, " " * ind + f"agents: {rendered}")
    return "\n".join(lines)


def remove_reach_entry(text, reach):
    lines = text.split("\n")
    b = _block(lines, "reaches", reach)
    if b is None:
        return text
    del lines[b[0]:b[1]]
    sec = _block(lines, "reaches")
    if sec is not None:
        body = [l for l in lines[sec[0] + 1:sec[1]] if l.strip() and not l.lstrip().startswith("#")]
        if not body:
            del lines[sec[0]:sec[1]]
    return "\n".join(lines)


def write_graph(path, text, dry):
    if dry:
        print(text)
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def cmd_enable(g, agent, dry):
    agents = g.get("agents") or {}
    if agent not in agents:
        die(f"no agents.{agent} in the graph (agents: {sorted(agents)})", 2)
    cur = agents_with_reach(g)
    if agent in cur:
        print(f"{agent}: already in reaches.{REACH_KEY}.agents")
        return 0
    new = cur + [agent]
    text = open(g["_path"], encoding="utf-8").read()
    text = set_agents_list(text, REACH_KEY, new)
    g2 = familia_yaml.loads(text) or {}
    errs = validate_reach_entry(g2, REACH_KEY, (g2.get("reaches") or {}).get(REACH_KEY) or {})
    try:
        import graph_types as gt
        errs += [e for e in gt.validate_types(g2) if "reach" in e.lower()]
    except Exception as e:  # noqa: BLE001
        errs.append(f"graph_types: {e}")
    if errs:
        die("refusing to write graph.yaml:\n  " + "\n  ".join(errs))
    write_graph(g["_path"], text, dry)
    print(("dry-run: would enable " if dry else "enabled ") + f"{agent} under reaches.{REACH_KEY}")
    return 0


def cmd_disable(g, agent, dry):
    cur = agents_with_reach(g)
    if agent not in cur:
        print(f"{agent}: not in reaches.{REACH_KEY}.agents")
        return 0
    new = [a for a in cur if a != agent]
    text = open(g["_path"], encoding="utf-8").read()
    text = remove_reach_entry(text, REACH_KEY) if not new else set_agents_list(text, REACH_KEY, new)
    write_graph(g["_path"], text, dry)
    print(("dry-run: would disable " if dry else "disabled ") + f"{agent} under reaches.{REACH_KEY}")
    return 0


def write_cli_wrapper(home, checkout, dry):
    bindir = os.path.join(home, "bin")
    wrapper = os.path.join(bindir, "agent-reach")
    q = shlex.quote(checkout)
    body = (
        "#!/bin/sh\n"
        "# Generated by familia scripts/agent_reach.py / hermes_harness link_reaches.\n"
        f"export PYTHONPATH={q}${{PYTHONPATH:+:$PYTHONPATH}}\n"
        'exec "${FAMILIA_AGENT_REACH_PY:-python3}" -m agent_reach.cli "$@"\n'
    )
    if dry:
        print(f"dry-run: would write {wrapper}")
        return wrapper
    os.makedirs(bindir, exist_ok=True)
    with open(wrapper, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(wrapper, 0o755)
    return wrapper


def link_reach_into_home(home, checkout=None, dry=False):
    checkout = checkout or pin_checkout()
    if not checkout:
        die(f"pin checkout missing; run: python3 scripts/sync_pins.py  (expects {ROOT}/{PIN_NAME})")
    skill = skill_dir(checkout)
    if not skill:
        die(f"skill missing under {checkout}/{SKILL_REL}")
    actions = []
    dst_root = os.path.join(home, "skills")
    dst = os.path.join(dst_root, "agent-reach")
    if dry:
        actions.append(f"symlink {skill} -> {dst}")
    else:
        os.makedirs(dst_root, exist_ok=True)
        if os.path.islink(dst) or os.path.exists(dst):
            if os.path.islink(dst) and os.path.realpath(dst) == os.path.realpath(skill):
                actions.append(f"ok {dst}")
            else:
                die(f"skills/agent-reach exists and is not our link to {skill}")
        else:
            os.symlink(skill, dst)
            actions.append(f"linked {dst}")
    write_cli_wrapper(home, checkout, dry)
    actions.append(f"wrapper {os.path.join(home, 'bin', 'agent-reach')}")
    mcp = {
        "mcpServers": {
            "agent-reach": {
                "command": "python3",
                "args": ["-m", "agent_reach.integrations.mcp_server"],
                "cwd": checkout,
                "timeout_ms": 30000,
            }
        }
    }
    tip = os.path.join(home, "agent-reach.mcp.example.json")
    if dry:
        actions.append(f"would write {tip}")
    else:
        with open(tip, "w", encoding="utf-8") as fh:
            json.dump(mcp, fh, indent=2)
            fh.write("\n")
        actions.append(f"wrote {tip}")
    return actions


def cmd_link(g, agent, home, dry):
    if agent and agent not in (g.get("agents") or {}):
        die(f"no agents.{agent} in the graph", 2)
    if agent and not reaches_for(g, agent):
        die(f"agent {agent!r} is not under any reaches.*.agents; "
            f"enable with: scripts/agent_reach.py enable --agent {agent}")
    if not home:
        if not agent:
            die("--home or --agent required")
        home = os.path.expanduser(f"~/.cache/familia/hermes-{agent}")
    for a in link_reach_into_home(home, dry=dry):
        print(a)
    print(f"HERMES_HOME tip: export PATH={os.path.join(home, 'bin')}:$PATH when launching hermes")
    return 0


def cmd_mcp_example():
    checkout = pin_checkout() or os.path.join(ROOT, PIN_NAME)
    print(json.dumps({
        "mcpServers": {
            "agent-reach": {
                "command": "python3",
                "args": ["-m", "agent_reach.integrations.mcp_server"],
                "cwd": checkout,
                "timeout_ms": 30000,
            }
        }
    }, indent=2))
    print("# Merge into code-bootstraps-llama.cpp config/mcp-servers.json (or a copy).", file=sys.stderr)
    print("# MCP here only exposes doctor/status; channel I/O is via the agent-reach CLI + skill.", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--graph", default=None, help="graph.yaml path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="pin / CLI / which agents are opted in")
    p.add_argument("--agent", default=None)

    p = sub.add_parser("enable", help="add agent to reaches.agent-reach.agents")
    p.add_argument("--agent", required=True)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("disable", help="remove agent from reaches.agent-reach.agents")
    p.add_argument("--agent", required=True)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("link", help="symlink skill + CLI wrapper into a HERMES_HOME")
    p.add_argument("--agent", default=None)
    p.add_argument("--home", default=None)
    p.add_argument("--dry-run", action="store_true")

    sub.add_parser("mcp-example", help="print mcpServers JSON for llama UI / code-bootstraps")

    a = ap.parse_args(argv)
    g = load_graph(a.graph) if a.cmd != "mcp-example" else {}
    if a.graph:
        g["_path"] = a.graph
    if a.cmd == "status":
        return cmd_status(g, a.agent)
    if a.cmd == "enable":
        return cmd_enable(g, a.agent, a.dry_run)
    if a.cmd == "disable":
        return cmd_disable(g, a.agent, a.dry_run)
    if a.cmd == "link":
        return cmd_link(g, a.agent, a.home, a.dry_run)
    if a.cmd == "mcp-example":
        return cmd_mcp_example()
    die(f"unknown command {a.cmd}", 2)


if __name__ == "__main__":
    sys.exit(main() or 0)
