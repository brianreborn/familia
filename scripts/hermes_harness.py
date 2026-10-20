#!/usr/bin/env python3
"""Graph-driven hermes-agent harness.

1. Validates graph.yaml (scripts/validate_graph.py); refuses to run on failure.
2. Renders a HERMES_HOME under ~/.cache/familia/hermes-<agent> from the graph:
   model base_url/alias of the agent's node, context_length == node per-slot
   ctx, compression on, context_engine enabled, every auxiliary task on the
   local node (no cloud fallback). Only non-secret settings are copied from
   ~/.hermes/config.yaml; ~/.hermes is only read, never written.
3. Starts the node's llama-server from `validate_graph.py --args` if it is not
   up, and waits until /props reports the expected n_ctx.
4. Execs /snap/bin/hermes-agent with that HERMES_HOME.
--escalate [--light NODE] puts a localhost escalation proxy (scripts/escalation_proxy.py,
docs/escalation.md) between hermes and the node; hermes then runs as a child, not exec.
--selftest-compaction runs hermes' own ContextCompressor on a synthetic
transcript against the node and checks that facts survive the summary.

usage: hermes_harness.py [--agent NAME] [--graph FILE] [--render-only | --selftest-compaction |
                          --escalate [--light NODE] [--no-swap-back]] [--accept-licenses|--yes]
                          [-h|--help] [-- HERMES-ARGS...]
Before a node is started, the licenses of the graph selection must be accepted (scripts/licenses.py
gate: prompts on a terminal; --accept-licenses / --yes or FAMILIA_ACCEPT_LICENSES=yes accepts).
Arguments for hermes-agent itself go after "--"; anything else unknown is an error (exit 2),
so a typo never renders a config and starts a server.
"""
import copy, json, os, re, subprocess, sys, time, urllib.request
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import validate_graph as vg  # noqa: E402

HERMES_BIN = os.environ.get("HERMES_BIN", "/snap/bin/hermes-agent")
HERMES_PY = "/snap/hermes-agent/current/bin/python3"
HERMES_SP = "/snap/hermes-agent/current/lib/python3.12/site-packages"
USER_HOME = os.path.expanduser("~/.hermes")
SECRET_RE = re.compile(r"(api_?key|token|secret|password|passwd|auth|cookie|credential)", re.I)
# Sections the harness owns; never inherited from the user's config.
OWNED = {"model", "auxiliary", "compression", "custom_providers", "providers", "smart_model_routing", "fallback_model"}
# Lean prompt profile (#85): the toolsets a coding agent on a small or old node needs. Long
# guidance stays reachable through the skills tools (skills_list / skill_view load on demand).
LEAN_TOOLSETS = ("terminal", "file", "todo", "clarify", "skills")
LEAN_RAM_MIB = 8192
# Aux tasks whose tool/prompt surface is unused on a lean coding node (#89 / #85).
# Kept in full profile. Dropping them shrinks the fixed prompt; MCP stays so official
# plugins (e.g. REA) still work when the graph opts them in (#92).
LEAN_AUX_DROP = ("web_extract", "tts_audio_tags", "triage_specifier", "kanban_decomposer",
                 "profile_describer", "goal_judge", "curator", "monitor", "title_generation")
# hermes re-probes the environment per session; this line changed between two launches minutes
# apart ("(no pip module)", pip=missing appear or not), so the cached prefix stops before it (#85).
UNSTABLE_LINES = ("Python toolchain:",)   # same line as the small-host floor in docs/ram-safety.md
AUX_TASKS = ["web_extract", "compression", "skills_hub", "approval", "mcp", "title_generation",
             "memory_query_rewrite", "tts_audio_tags", "triage_specifier", "kanban_decomposer",
             "profile_describer", "goal_judge", "curator", "monitor"]


def die(msg):
    print(f"hermes.sh: {msg}", file=sys.stderr); sys.exit(1)


def strip_secrets(v):
    if isinstance(v, dict):
        return {k: strip_secrets(x) for k, x in v.items() if not SECRET_RE.search(str(k))}
    if isinstance(v, list):
        return [strip_secrets(x) for x in v]
    return v


def load_graph(path):
    g = yaml.safe_load(open(path)); g["_path"] = path
    errs, _ = vg.validate(g)
    for e in errs: print(f"graph: ERROR: {e}", file=sys.stderr)
    if errs: die("graph validation failed; not launching")
    return g


def node_for(g, agent):
    a = (g.get("agents") or {}).get(agent) or die(f"agent {agent!r} not in graph")
    if "aliases" in a:  # schema v2: agents.X.aliases.main -> top-level aliases -> node
        target = a["aliases"].get("main") or die(f"agent {agent}: no 'main' alias")
        al = (g.get("aliases") or {}).get(target)
        name = al["node"] if al else target
    else:  # schema v1: agents.X.edges.model -> node aliases
        target = (a.get("edges") or {}).get("model") or die(f"agent {agent}: no 'model' edge")
        aliases = {al: k for k, n in g["nodes"].items() for al in n.get("aliases", [])}
        name = aliases.get(target, target)
    return a, name, g["nodes"][name], target


def bind(n):
    return n.get("bind") or n.get("host", "127.0.0.1")


def prompt_profile(g, a, n):
    """agents.<a>.prompt_profile: lean | full | auto (default). auto = lean on a phone or a host
    with ram_mib < 8192, where the full 27-tool prompt costs ~12.5k tokens of CPU prefill."""
    p = a.get("prompt_profile", "auto")
    if p != "auto":
        return p
    h = (g.get("hosts") or {}).get(n.get("host"), {})
    return "lean" if h.get("kind") == "phone" or (h.get("ram_mib") or 0) < LEAN_RAM_MIB else "full"


def lean_toolsets(cfg):
    """Only ever narrows: toolsets the user did not enable are never added."""
    have = ((cfg.get("platform_toolsets") or {}).get("cli"))
    return [t for t in have if t in LEAN_TOOLSETS] if isinstance(have, list) else list(LEAN_TOOLSETS)


def link_plugins(agent_cfg, home):
    """Symlink selected portable plugins from ~/.hermes/plugins into the rendered HERMES_HOME.

    agents.<a>.plugins:
      omit / []     — leave plugins/ untouched (no links added)
      ["*"]         — link every directory under ~/.hermes/plugins
      ["rea", ...]  — link only those names (must exist under ~/.hermes/plugins)

    Never copies bytes; never installs; never enables a plugin the user has not
    already installed into ~/.hermes/plugins. Self-improve cannot reach this path.
    """
    want = agent_cfg.get("plugins")
    if not want:
        return []
    src_root = os.path.join(USER_HOME, "plugins")
    dst_root = os.path.join(home, "plugins")
    os.makedirs(dst_root, exist_ok=True)
    if want == ["*"] or want == "*":
        names = sorted(e for e in os.listdir(src_root) if os.path.isdir(os.path.join(src_root, e))) if os.path.isdir(src_root) else []
    else:
        names = list(want)
    linked = []
    for name in names:
        if not isinstance(name, str) or not name or name.startswith(".") or "/" in name or "\\" in name:
            die(f"plugins: invalid name {name!r}")
        src = os.path.join(src_root, name)
        dst = os.path.join(dst_root, name)
        if not os.path.isdir(src):
            die(f"plugins: {name!r} not installed under ~/.hermes/plugins "
                f"(install with: hermes plugins install {name})")
        if os.path.islink(dst) or os.path.exists(dst):
            if os.path.islink(dst) and os.path.realpath(dst) == os.path.realpath(src):
                linked.append(name); continue
            die(f"plugins: {dst} exists and is not our link to {src}")
        os.symlink(src, dst)
        linked.append(name)
    return linked



def render(g, agent, user_cfg_path=os.path.join(USER_HOME, "config.yaml"), base_override=None):
    a, name, n, alias = node_for(g, agent)
    base = base_override or f"http://{bind(n)}:{n['port']}/v1"
    user = {}
    if os.path.isfile(user_cfg_path):
        user = yaml.safe_load(open(user_cfg_path)) or {}
    cfg = {k: strip_secrets(copy.deepcopy(v)) for k, v in user.items() if k not in OWNED}
    ctx = a["context_length"]
    comp = a.get("compression") or {}
    cfg["model"] = {"provider": "custom", "base_url": base, "default": alias,
                    "context_length": ctx, "api_key": "local"}
    cfg["compression"] = {"enabled": True,
                          "threshold": comp.get("threshold", 0.75),
                          "target_ratio": comp.get("target_ratio", 0.20),
                          "protect_first_n": comp.get("protect_first_n", 3),
                          "protect_last_n": comp.get("protect_last_n", 8)}
    ag = cfg.setdefault("agent", {})
    ag["disabled_toolsets"] = [t for t in ag.get("disabled_toolsets", []) or [] if t != "context_engine"]
    aux = {"transient_retries": 2}
    for t in AUX_TASKS:
        aux[t] = {"provider": "custom", "model": alias, "base_url": base, "api_key": "local",
                  "timeout": comp.get("aux_timeout", 3600)}
    cfg["auxiliary"] = aux
    if prompt_profile(g, a, n) == "lean":
        cfg["platform_toolsets"] = dict(cfg.get("platform_toolsets") or {}, cli=lean_toolsets(cfg))
        aux = cfg.get("auxiliary") or {}
        for t in LEAN_AUX_DROP:
            aux.pop(t, None)
        cfg["auxiliary"] = aux
    # Official / portable Hermes plugins (Agent Plugins v1) live under HERMES_HOME/plugins.
    # Opt-in via agents.<name>.plugins: ["rea"] or ["*"] to link from ~/.hermes/plugins (#92).
    # Self-improve never adds plugins (scripts/self_improve.py gate).
    home = os.path.expanduser(f"~/.cache/familia/hermes-{agent}")
    if os.path.realpath(home) == os.path.realpath(USER_HOME):
        die("refusing to render into ~/.hermes")
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "config.yaml"), "w") as f:
        f.write("# Generated by familia scripts/hermes_harness.py from graph.yaml. Do not edit.\n")
        yaml.safe_dump(cfg, f, sort_keys=False)
    link_plugins(a, home)
    return home, base, n, name


def props(n):
    url = f"http://{bind(n)}:{n['port']}/props"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.load(r)
    except Exception:
        return None


ACCEPT_LICENSES = False   # --accept-licenses / --yes


def license_gate(g):
    """Before a node is started: the licenses of the graph selection must be accepted
    (scripts/licenses.py gate; docs/licenses.md). Once per run."""
    if getattr(license_gate, "done", False):
        return
    lp = os.path.join(ROOT, "scripts", "licenses.py")
    if not os.path.isfile(lp):
        die("scripts/licenses.py not found; licenses must be accepted before a model is started")
    cmd = [sys.executable, lp, "gate"] + (["--yes"] if ACCEPT_LICENSES else [])
    if g.get("_path"):
        cmd += ["--graph", g["_path"]]
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        die("licenses not accepted (scripts/licenses.py exit %d); no model was started. Accept with "
            "scripts/licenses.py review, or pass --accept-licenses" % rc)
    license_gate.done = True


def ensure_server(g, name, n, timeout=900):
    want = n["ctx"] // n["parallel"]
    p = props(n)
    if p is None:
        license_gate(g)
        args = vg.server_args(g, name)
        logd = os.path.expanduser("~/.cache/familia/logs"); os.makedirs(logd, exist_ok=True)
        log = open(os.path.join(logd, f"{name}.log"), "ab")
        print(f"hermes.sh: starting node {name}: {' '.join(args)}", file=sys.stderr)
        subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True, env=vg.server_env(g, name))
        t0 = time.time()
        while (p := props(n)) is None or "default_generation_settings" not in p:
            if time.time() - t0 > timeout: die(f"node {name} did not come up on port {n['port']}")
            time.sleep(3)
    got = (p.get("default_generation_settings") or {}).get("n_ctx")
    if got != want:
        die(f"node {name} on port {n['port']} reports n_ctx {got}, graph expects per-slot {want}; "
            "something else is on that port or it was started with other args")
    return got


PREFIX_CHILD = r'''
import json, os, sys
sys.path.insert(0, os.environ["HERMES_SP"])
from hermes_cli.prompt_size import _build_inspection_agent
from agent.system_prompt import build_system_prompt, build_system_prompt_parts
a = _build_inspection_agent("cli")
json.dump({"system": build_system_prompt(a), "volatile": build_system_prompt_parts(a).get("volatile", ""),
           "tools": a.tools}, sys.stdout)
'''


def hermes_prefix(home):
    """The system prompt + tool schemas hermes will send, built offline by hermes itself. A snap
    hermes is asked inside its own snap environment (outside it, fewer tools are detected)."""
    env = dict(os.environ, HERMES_HOME=home, HERMES_SP=HERMES_SP, FAMILIA_PREFIX_CHILD=PREFIX_CHILD)
    if HERMES_BIN.startswith("/snap/bin/"):
        cmd = ["snap", "run", "--shell", os.path.basename(HERMES_BIN), "-c", '"$SNAP/bin/python3" -c "$FAMILIA_PREFIX_CHILD"']
    else:
        cmd = [HERMES_PY, "-c", PREFIX_CHILD]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:])
    return json.loads(r.stdout)


def warm_prompt(g, name, n, home):
    """Nodes with slot_save: restore the fixed prompt prefix from disk, or prefill and save it once
    (scripts/prompt_cache.py, #85). Best effort: any failure only means a slower first turn."""
    if not n.get("slot_save"):
        return None
    import prompt_cache
    base = f"http://{bind(n)}:{n['port']}"
    try:
        d = hermes_prefix(home)
        text = prompt_cache.stable_prefix(base, d["system"], d["tools"], d.get("volatile", ""), unstable=UNSTABLE_LINES)
        return prompt_cache.warm(base, prompt_cache.prefix_tokens(base, text), tag=name)[0]
    except Exception as e:
        print(f"hermes.sh: prompt cache skipped ({e})", file=sys.stderr)
        return None


def chat(base, alias, messages, max_tokens=400):
    body = json.dumps({"model": alias, "messages": messages, "max_tokens": max_tokens,
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(base + "/chat/completions", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=7200) as r:
        return json.load(r)["choices"][0]["message"].get("content") or ""


SELFTEST_CHILD = r'''
import json, os, sys
sys.path.insert(0, os.environ["HERMES_SP"])
from agent.context_compressor import ContextCompressor
spec = json.load(sys.stdin)
cc = ContextCompressor(model=spec["alias"], threshold_percent=0.75, protect_first_n=1,
                       protect_last_n=2, summary_target_ratio=spec["target_ratio"], quiet_mode=True,
                       base_url=spec["base"], api_key="local", config_context_length=spec["ctx"],
                       provider="custom")
out = cc.compress(spec["messages"], force=True)
json.dump({"messages": out}, sys.stdout)
'''


def selftest(g, agent):
    """Cheap compaction proof: synthetic transcript, forced compress, recall check."""
    home, base, n, name = render(g, agent)
    ensure_server(g, name, n)
    _, _, _, alias = node_for(g, agent)
    ctx = g["agents"][agent]["context_length"]
    words = ["amber", "birch", "cobalt", "delta", "ember", "fjord"]
    filler = ("The familia graph declares nodes, runtimes and agent edges explicitly. " * 40).strip()
    msgs = [{"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "We will record codewords. Acknowledge."},
            {"role": "assistant", "content": "Acknowledged."}]
    for i, w in enumerate(words, 1):
        msgs += [{"role": "user", "content": f"Note {i}: codeword {i} is {w}. Background: {filler}"},
                 {"role": "assistant", "content": f"Recorded codeword {i}: {w}."}]
    msgs += [{"role": "user", "content": "Thanks. Keep them in mind."},
             {"role": "assistant", "content": "Will do."}]
    # Tail budget scales with the window; a tiny target_ratio keeps it below the transcript.
    spec = {"alias": alias, "base": base, "ctx": ctx, "target_ratio": 0.02, "messages": msgs}
    env = dict(os.environ, HERMES_HOME=home, HERMES_SP=HERMES_SP)
    t0 = time.time()
    r = subprocess.run([HERMES_PY, "-c", SELFTEST_CHILD], input=json.dumps(spec), capture_output=True,
                       text=True, env=env, timeout=7200)
    if r.returncode != 0:
        die(f"selftest: compressor failed:\n{r.stderr[-2000:]}")
    out = json.loads(r.stdout)["messages"]
    before, after = sum(len(m["content"]) for m in msgs), sum(len(str(m.get("content", ""))) for m in out)
    print(f"selftest: compress {len(msgs)} -> {len(out)} messages, {before} -> {after} chars, {time.time()-t0:.0f}s")
    if len(out) >= len(msgs) or after >= before:
        die("selftest: FAIL, compaction did not shrink the transcript")
    q = out + [{"role": "user", "content": "List codewords 1 to 6 in order, comma-separated, nothing else."}]
    t1 = time.time(); ans = chat(base, alias, q)
    found = [w for w in words if w in ans.lower()]
    print(f"selftest: answer after compaction ({time.time()-t1:.0f}s): {ans.strip()[:300]!r}")
    print(f"selftest: recalled {len(found)}/{len(words)}: {found}")
    if len(found) < len(words) - 1:
        die("selftest: FAIL, model lost the facts after compaction")
    print("selftest: PASS")


def run_escalating(g, agent, light, swap_back, rest):
    import socket, escalation_proxy as EP, registry
    local = socket.gethostname().split(".")[0]
    if local not in g["hosts"]: local = g["nodes"][light]["host"]
    def ensure(nm):
        try: ensure_server(g, nm, g["nodes"][nm]); return True
        except SystemExit as e: print(f"hermes.sh: {e}", file=sys.stderr); return False
    ensure(light) or die(f"light node {light} did not start")
    esc = EP.Escalator(g, light, registry.load(), local, ensure=ensure, swap_back=swap_back)
    srv = EP.serve(esc)
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    home, _, _, _ = render(g, agent, base_override=base)
    warm_prompt(g, light, g["nodes"][light], home)
    print(f"hermes.sh: escalation proxy {base} light={light} targets={g['nodes'][light].get('escalates_to')}", file=sys.stderr)
    return subprocess.call([HERMES_BIN] + rest, env=dict(os.environ, HERMES_HOME=home))


USAGE = __doc__.split("usage: ", 1)[1].strip()


def parse_argv(argv):
    """-> (agent, graph_path, mode, light, swap_back, rest). SystemExit(0) for --help,
    SystemExit(2) for an unknown argument or a missing value."""
    agent, graph_path, rest = "hermes", os.path.join(ROOT, "graph.yaml"), []
    mode, light, swap_back = "run", None, True
    it = iter(argv)

    def val(x):
        v = next(it, None)
        if v is None or v.startswith("-"):
            print(f"hermes_harness.py: {x} needs a value\nusage: {USAGE}", file=sys.stderr); raise SystemExit(2)
        return v
    for x in it:
        if x in ("-h", "--help"): print(__doc__.strip()); raise SystemExit(0)
        elif x == "--agent": agent = val(x)
        elif x == "--graph": graph_path = val(x)
        elif x == "--render-only": mode = "render"
        elif x == "--selftest-compaction": mode = "selftest"
        elif x == "--escalate": mode = "escalate"
        elif x == "--light": light = val(x)
        elif x == "--no-swap-back": swap_back = False
        elif x in ("--accept-licenses", "--yes"):
            global ACCEPT_LICENSES
            ACCEPT_LICENSES = True
        elif x == "--": rest = list(it); break
        else:
            print(f"hermes_harness.py: unknown argument {x!r} (hermes-agent arguments go after --)\nusage: {USAGE}", file=sys.stderr)
            raise SystemExit(2)
    return agent, graph_path, mode, light, swap_back, rest


def main(argv):
    agent, graph_path, mode, light, swap_back, rest = parse_argv(argv)
    g = load_graph(graph_path)
    if mode == "selftest":
        return selftest(g, agent)
    home, base, n, name = render(g, agent)
    print(f"hermes.sh: HERMES_HOME={home} model={base}", file=sys.stderr)
    if mode == "render":
        return 0
    if mode == "escalate":
        return run_escalating(g, agent, light or name, swap_back, rest)
    ensure_server(g, name, n)
    warm_prompt(g, name, n, home)
    os.environ["HERMES_HOME"] = home
    os.execv(HERMES_BIN, [HERMES_BIN] + rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
