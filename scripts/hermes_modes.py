#!/usr/bin/env python3
"""hermes.sh front end: two modes over scripts/hermes_harness.py.

GRAPH mode (default; same behaviour as before): the agent's graph wiring. Main/auxiliary
  aliases from graph.yaml, every declared node, and the escalation proxy (docs/escalation.md)
  when the main node declares escalates_to with escalation.mode not off (suggest by default,
  first cross-host escalation asks consent). --escalate/--light/--no-swap-back as before.
SINGLE-MODEL mode (--mode single --model NODE, or just --model NODE): hermes against that
  one node. Own HERMES_HOME (~/.cache/familia/hermes-<agent>@<node>), context_length = the
  node's per-slot ctx, compression on, auxiliary tasks on the same node, no aliases, no proxy.
  Refuses nodes under the agent's min_ctx (hermes-agent's 64K floor).

Self-improving harness (optional, docs/harness2.md): when graph.yaml has a harnesses.<T>
descriptor with agent: <this agent> and a self_improve entry with mode != "off" targeting it
(or with --self-improve), the launcher runs `scripts/harness2.py sync` as a subprocess before
starting hermes so the accepted harness version is in place. Nothing is imported from it;
if it is absent, hermes starts unchanged. Harness² itself never needs hermes.

Enabled skills (agents.<agent>.skills, scripts/skills.py, docs/skills.md) are linked into
HERMES_HOME/skills/<id> in both modes (`scripts/skills.py paths`); existing entries are kept.

Licenses of the graph selection are accepted before a node starts (scripts/licenses.py gate;
--accept-licenses / --yes accepts).

usage: hermes.sh [--graph-mode | --model NODE | --mode graph|single] [--agent NAME] [--graph FILE]
                 [--self-improve] [--accept-licenses|--yes]
                 [--render-only | --selftest-compaction | --escalate [--light NODE] [--no-swap-back] | --no-escalate]
                 [-h|--help] [-- HERMES-ARGS...]
  --graph-mode is the same as --mode graph (the default); --graph FILE only picks which graph.yaml.
example: scripts/hermes.sh --model coder --render-only
       scripts/hermes.sh --model angel-coder --render-only   # FreeBSD angel smoke (host-scoped files)
       hermes.sh harness2 COMMAND ...    Harness² review CLI (scripts/harness2.py); launches nothing
"""
import copy, os, socket, subprocess, sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
USAGE = __doc__.split("usage: ", 1)[1].strip()
GRAPH_ONLY = ("--escalate", "--light", "--no-swap-back", "--no-escalate")
NOT_CHAT = {"embed", "diffusion"}


def usage_err(msg):
    print(f"hermes.sh: {msg}\nusage: {USAGE}", file=sys.stderr); raise SystemExit(2)


def parse(argv):
    o = {"mode": None, "model": None, "agent": "hermes", "graph": os.path.join(ROOT, "graph.yaml"),
         "action": "run", "light": None, "swap_back": True, "escalate": None, "self_improve": False,
         "accept": False, "rest": [], "seen": []}
    it = iter(argv)
    def val(x):
        v = next(it, None)
        if v is None or v.startswith("-"): usage_err(f"{x} needs a value")
        return v
    for x in it:
        if x in ("-h", "--help"): print(__doc__.strip()); raise SystemExit(0)
        elif x == "--mode":
            o["mode"] = val(x)
            if o["mode"] not in ("graph", "single"): usage_err(f"--mode must be graph or single, got {o['mode']!r}")
        elif x == "--graph-mode":
            if o["mode"] == "single": usage_err("--graph-mode conflicts with --mode single")
            o["mode"] = "graph"
        elif x in ("--accept-licenses", "--yes"): o["accept"] = True
        elif x == "--model": o["model"] = val(x)
        elif x == "--agent": o["agent"] = val(x)
        elif x == "--graph": o["graph"] = val(x)
        elif x == "--self-improve": o["self_improve"] = True
        elif x == "--render-only": o["action"] = "render"
        elif x == "--selftest-compaction": o["action"] = "selftest"
        elif x == "--escalate": o["escalate"] = True
        elif x == "--no-escalate": o["escalate"] = False
        elif x == "--light": o["light"] = val(x)
        elif x == "--no-swap-back": o["swap_back"] = False
        elif x == "--": o["rest"] = list(it); break
        else: usage_err(f"unknown argument {x!r} (hermes-agent arguments go after --)")
        if x.startswith("--"): o["seen"].append(x)
    if o["mode"] is None: o["mode"] = "single" if o["model"] else "graph"
    if o["mode"] == "graph" and o["model"]:
        usage_err("--model selects single-model mode; drop --graph-mode/--mode graph (graph mode uses the agent's aliases)")
    if o["mode"] == "single":
        bad = [f for f in o["seen"] if f in GRAPH_ONLY]
        if bad: usage_err(f"{', '.join(bad)}: graph mode only (single-model mode has no router or escalation proxy)")
    if o["action"] != "run" and o["escalate"]:
        usage_err("--escalate cannot combine with --render-only or --selftest-compaction")
    if (o["light"] or not o["swap_back"]) and o["escalate"] is not True:
        usage_err("--light and --no-swap-back need --escalate")
    return o


def slot(n): return n["ctx"] // n["parallel"]


def eligible(g, floor):
    return [f"{k} ({slot(n)})" for k, n in g["nodes"].items()
            if n.get("status") == "active" and slot(n) >= floor
            and (g["models"].get(n["model"]) or {}).get("role") not in NOT_CHAT]


def single_agent(g, agent, node, *, enforce_min_ctx=True):
    """-> (graph copy with a synthetic agent '<agent>@<node>', its name). Exits on refusal.

    enforce_min_ctx=False (--render-only): warn when below min_ctx so a host can smoke-render
    without meeting the floor yet. Launch still enforces the floor
    (hermes-agent MINIMUM_CONTEXT_LENGTH is 64_000 as of upstream).
    """
    a = (g.get("agents") or {}).get(agent) or usage_err(f"agent {agent!r} not in graph")
    n = (g.get("nodes") or {}).get(node)
    if n is None: usage_err(f"--model {node!r}: no such node (nodes: {sorted(g['nodes'])})")
    floor = a["min_ctx"]
    role = (g["models"].get(n["model"]) or {}).get("role")
    if role in NOT_CHAT: sys.exit(f"hermes.sh: node {node} serves a role:{role} model; hermes needs a chat model. Eligible: {', '.join(eligible(g, floor)) or 'none'}")
    if n.get("status") != "active": sys.exit(f"hermes.sh: node {node} is status {n.get('status')}, not active")
    if slot(n) < floor:
        msg = (f"hermes.sh: node {node} per-slot ctx {slot(n)} (ctx {n['ctx']} / parallel {n['parallel']}) is below "
               f"agent {agent} min_ctx {floor} (hermes-agent refuses smaller windows). "
               f"Eligible: {', '.join(eligible(g, floor)) or 'none'}; or raise nodes.{node}.ctx (validate_graph checks RAM)")
        if enforce_min_ctx:
            sys.exit(msg)
        print(msg + " — continuing for --render-only only", file=sys.stderr)
    here = socket.gethostname().split(".")[0]
    if here in (g.get("hosts") or {}) and n["host"] != here:
        sys.exit(f"hermes.sh: node {node} is on {n['host']}, this is {here}; single-model mode starts the node locally")
    alias = next((k for k, al in (g.get("aliases") or {}).items() if al.get("node") == node), None)
    if alias is None and node in (g.get("aliases") or {}): usage_err(f"alias {node!r} names another node; cannot address node {node} directly")
    g2 = copy.deepcopy(g); name = f"{agent}@{node}"
    g2["agents"][name] = dict(copy.deepcopy(a), context_length=slot(n), aliases={"main": alias or node, "auxiliary": alias or node})
    return g2, name


def self_improve_targets(g, agent):
    """Harness descriptors for this agent and whether a self_improve entry enables them (data only)."""
    out = []
    for t, h in (g.get("harnesses") or {}).items():
        if not isinstance(h, dict) or h.get("agent") != agent: continue
        on = any(t in (s.get("targets") or []) and s.get("mode") not in ("off", False, None)
                 for s in (g.get("self_improve") or {}).values() if isinstance(s, dict))
        out.append((t, on))
    return out


def pickup(g, o, agent, into=None):
    tool = os.path.join(ROOT, "scripts", "harness2.py")
    for t, on in self_improve_targets(g, agent):
        if not (on or o["self_improve"]): continue
        if not os.path.isfile(tool):
            print(f"hermes.sh: self-improve target {t} declared but scripts/harness2.py is absent; starting without it", file=sys.stderr); continue
        cmd = [sys.executable, tool, "--graph", o["graph"], "sync", "--target", t] + (["--into", into] if into else [])
        r = subprocess.run(cmd, capture_output=True, text=True)
        msg = (r.stdout + r.stderr).strip()
        print(f"hermes.sh: self-improve ({t}): {msg if r.returncode == 0 else 'sync failed, starting without it: ' + msg}", file=sys.stderr)
    if o["self_improve"] and not self_improve_targets(g, agent):
        sys.exit(f"hermes.sh: --self-improve: no harnesses.* entry has agent: {agent} (docs/harness2.md)")


def link_skills(raw, agent, home):
    """Link agents.<agent>.skills folders into HOME/skills/<id> (docs/skills.md, #72). Never replaces
    an existing entry; a missing skills.py or a skill without files is a note, not a failure."""
    a = (raw.get("agents") or {}).get(agent) or {}
    if not a.get("skills"): return
    tool = os.path.join(ROOT, "scripts", "skills.py")
    if not os.path.isfile(tool):
        print("hermes.sh: skills listed but scripts/skills.py is absent; starting without them", file=sys.stderr); return
    r = subprocess.run([sys.executable, tool, "paths", "--agent", agent], capture_output=True, text=True,
                       env=dict(os.environ, FAMILIA_GRAPH=os.path.abspath(raw.get("_path") or os.path.join(ROOT, "graph.yaml"))))
    if r.stderr.strip(): print(r.stderr.strip(), file=sys.stderr)
    d = os.path.join(home, "skills"); os.makedirs(d, exist_ok=True); linked = []
    for src in [l.strip() for l in r.stdout.splitlines() if l.strip()]:
        dst = os.path.join(d, os.path.basename(src.rstrip("/")))
        if os.path.islink(dst) and os.path.realpath(dst) == os.path.realpath(src): linked.append(os.path.basename(dst)); continue
        if os.path.lexists(dst):
            print(f"hermes.sh: skills: {dst} exists and is not a link to {src}; left as is", file=sys.stderr); continue
        os.symlink(src, dst); linked.append(os.path.basename(dst))
    print(f"hermes.sh: skills linked into {d}: {', '.join(linked) or 'none'}", file=sys.stderr)


def main(argv):
    o = parse(argv)
    import hermes_harness as hh
    agent = o["agent"]
    if o["accept"]: hh.ACCEPT_LICENSES = True
    if o["mode"] == "graph":
        raw = yaml.safe_load(open(o["graph"])); raw["_path"] = o["graph"]
        a = (raw.get("agents") or {}).get(agent)
        fwd = ["--agent", agent, "--graph", o["graph"]] + (["--accept-licenses"] if o["accept"] else [])
        if o["action"] == "render": fwd.append("--render-only")
        elif o["action"] == "selftest": fwd.append("--selftest-compaction")
        if a and o["action"] == "run" and o["escalate"] is None:
            tgt = (raw.get("aliases") or {}).get((a.get("aliases") or {}).get("main"), {})
            n = (raw.get("nodes") or {}).get(tgt.get("node"), {})
            if n.get("escalates_to") and (n.get("escalation") or {}).get("mode", "suggest") != "off":
                o["escalate"] = True
        if o["escalate"]:
            fwd.append("--escalate")
            if o["light"]: fwd += ["--light", o["light"]]
            if not o["swap_back"]: fwd.append("--no-swap-back")
        print(f"hermes.sh: mode=graph agent={agent} escalation={'proxy' if o['escalate'] else 'off'}", file=sys.stderr)
        if a:
            pickup(raw, o, agent)
            link_skills(raw, agent, os.path.expanduser(f"~/.cache/familia/hermes-{agent}"))
        return hh.main(fwd + (["--"] + o["rest"] if o["rest"] else []))
    # Scope weight checks to the node's host (angel must not require box GGUFs).
    peek = yaml.safe_load(open(o["graph"])) or {}
    peek["_path"] = o["graph"]
    node = o["model"]
    if not node:
        # Need aliases to pick default node; schema-only load first.
        g0 = hh.load_graph(o["graph"], check_files=False)
        node = hh.node_for(g0, agent)[1]
    npeek = (peek.get("nodes") or {}).get(node) or {}
    scope = npeek.get("host")
    g = hh.load_graph(o["graph"], check_files=(o["action"] != "render"),
                      host=None if o["action"] == "render" else scope)
    g2, name = single_agent(g, agent, node, enforce_min_ctx=(o["action"] != "render"))
    home = os.path.expanduser(f"~/.cache/familia/hermes-{name}")
    print(f"hermes.sh: mode=single agent={agent} node={node} ctx={g2['agents'][name]['context_length']} router=none compression=on", file=sys.stderr)
    pickup(g, o, agent, into=home)
    link_skills(g, agent, home)
    if o["action"] == "selftest":
        hh.ensure_hermes()
        return hh.selftest(g2, name)
    home, base, n, nname = hh.render(g2, name)
    print(f"hermes.sh: HERMES_HOME={home} model={base}", file=sys.stderr)
    if o["action"] == "render": return 0
    hh.ensure_hermes()
    hh.ensure_server(g2, nname, n)
    hh.warm_prompt(g2, nname, n, home)
    os.environ["HERMES_HOME"] = home
    os.execv(hh.HERMES_BIN, [hh.HERMES_BIN] + o["rest"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
