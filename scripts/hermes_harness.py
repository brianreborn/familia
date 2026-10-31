#!/usr/bin/env python3
"""Graph-driven hermes-agent harness.

1. Validates graph.yaml (scripts/validate_graph.py); refuses to run on failure.
2. Renders a HERMES_HOME under ~/.cache/familia/hermes-<agent> from the graph:
   model base_url/alias of the agent's node, context_length == node per-slot
   ctx, compression on, context_engine enabled, every auxiliary task on the
   local node (no cloud fallback). Only non-secret settings are copied from
   ~/.hermes/config.yaml; ~/.hermes is only read, never written.
3. Requires the node's llama-server already up (DETACH_MODE=screen-attached /
   scripts/serve.sh). Checks /props n_ctx and, when graph has server_tools,
   that /tools is not feature_disabled. Never daemon-spawns llama-server.
4. Execs hermes-agent (resolved: snap, FreeBSD ports, or HERMES_BIN) with that HERMES_HOME.
   --client cli|desktop|webapp (default cli) selects the frontend surface: plain CLI,
   native Hermes Desktop (`hermes desktop`), or desktop-as-webapp (`hermes webapp`).
   See docs/hermes-clients.md. Equal-tier frontends; not backend/flagship.
--escalate [--light NODE] puts a localhost escalation proxy (scripts/escalation_proxy.py,
docs/escalation.md) between hermes and the node; hermes then runs as a child, not exec.
--selftest-compaction runs hermes' own ContextCompressor on a synthetic
transcript against the node and checks that facts survive the summary.

usage: hermes_harness.py [--agent NAME] [--graph FILE] [--client cli|desktop|webapp]
                          [--render-only | --selftest-compaction |
                          --escalate [--light NODE] [--no-swap-back]] [--accept-licenses|--yes]
                          [-h|--help] [-- HERMES-ARGS...]
Before a node is started, the licenses of the graph selection must be accepted (scripts/licenses.py
gate: prompts on a terminal; --accept-licenses / --yes or FAMILIA_ACCEPT_LICENSES=yes accepts).
Arguments for hermes-agent itself go after "--"; anything else unknown is an error (exit 2),
so a typo never renders a config and starts a server.
"""
import copy, glob, json, os, re, shutil, subprocess, sys, time, urllib.error, urllib.request
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import validate_graph as vg  # noqa: E402
import oom_adj  # noqa: E402
import familia_auth  # noqa: E402

# Default Linux snap layout (kept when /snap/bin/hermes-agent exists).
SNAP_BIN = "/snap/bin/hermes-agent"
SNAP_PY = "/snap/hermes-agent/current/bin/python3"
SNAP_SP = "/snap/hermes-agent/current/lib/python3.12/site-packages"
# FreeBSD ports misc/hermes-agent: wrappers in PREFIX/bin, source tree under PREFIX/lib/hermes-agent
# (not site-packages — see ports wrapper.in). Angel/Uriel: pkg hermes-agent.
FREEBSD_BIN = "/usr/local/bin/hermes-agent"
FREEBSD_LIB = "/usr/local/lib/hermes-agent"

HERMES_BIN = HERMES_PY = HERMES_SP = None  # set by resolve_hermes() below


def _path_exists(p):
    return bool(p) and os.path.exists(p)


def _read_shebang(path):
    """Return interpreter from a #! line, or None."""
    try:
        with open(path, "rb") as f:
            line = f.readline(256)
    except OSError:
        return None
    if not line.startswith(b"#!"):
        return None
    parts = line[2:].decode("utf-8", "replace").strip().split()
    if not parts:
        return None
    if os.path.basename(parts[0]) == "env" and len(parts) >= 2:
        return shutil.which(parts[1]) or parts[1]
    return parts[0]


def _can_import_hermes_cli(py, sp, run=subprocess.run):
    """True if `import hermes_cli` works with sp on sys.path (empty sp = bare import)."""
    if not py:
        return False
    code = (
        "import sys\n"
        + (f"sys.path.insert(0, {sp!r})\n" if sp else "")
        + "import hermes_cli\n"
    )
    try:
        r = run([py, "-c", code], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _discover_sp_via_import(py, run=subprocess.run):
    """Parent dir of the hermes_cli package (site-packages or FreeBSD HERMES_LIBDIR)."""
    code = (
        "import hermes_cli, os\n"
        "print(os.path.dirname(os.path.dirname(os.path.abspath(hermes_cli.__file__))))\n"
    )
    try:
        r = run([py, "-c", code], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip()
    return out or None


def _sp_candidates(bin_path, py, exists=_path_exists):
    """Likely HERMES_SP roots: FreeBSD libdir, venv site-packages, PREFIX/lib/hermes-agent."""
    out = []
    if exists(FREEBSD_LIB):
        out.append(FREEBSD_LIB)
    if py:
        root = os.path.dirname(os.path.dirname(os.path.abspath(py)))
        out.extend(sorted(glob.glob(os.path.join(root, "lib", "python*", "site-packages"))))
        out.extend(sorted(glob.glob(os.path.join(root, "Lib", "site-packages"))))
    if bin_path:
        prefix = os.path.dirname(os.path.dirname(os.path.abspath(bin_path)))
        out.append(os.path.join(prefix, "lib", "hermes-agent"))
    # de-dupe, keep order
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _derive_py(bin_path, exists=_path_exists, which=shutil.which):
    if bin_path and str(bin_path).startswith("/snap/bin/"):
        return SNAP_PY
    sheb = _read_shebang(bin_path) if bin_path and exists(bin_path) else None
    if sheb and exists(sheb):
        return sheb
    if bin_path:
        sibling = os.path.join(os.path.dirname(os.path.abspath(bin_path)), "python3")
        if exists(sibling):
            return sibling
    return which("python3") or which("python") or sys.executable


def _derive_sp(bin_path, py, exists=_path_exists, run=subprocess.run):
    if bin_path and str(bin_path).startswith("/snap/bin/"):
        return SNAP_SP
    for cand in _sp_candidates(bin_path, py, exists=exists):
        if exists(cand) and _can_import_hermes_cli(py, cand, run=run):
            return cand
    # FreeBSD ports: libdir is HERMES_SP (wrapper inserts it; not site-packages).
    if bin_path and (str(bin_path) == FREEBSD_BIN or str(bin_path).endswith("/hermes-agent")
                     or str(bin_path).endswith("/hermes")) and exists(FREEBSD_LIB):
        return FREEBSD_LIB
    discovered = _discover_sp_via_import(py, run=run)
    if discovered and exists(discovered):
        return discovered
    if exists(FREEBSD_LIB):
        return FREEBSD_LIB
    return None


def resolve_hermes(environ=None, *, exists=_path_exists, which=shutil.which,
                   system=None, run=subprocess.run, missing="defaults"):
    """Resolve HERMES_BIN / HERMES_PY / HERMES_SP.

    Order: explicit env overrides always win per-variable; then Linux snap if
    present; then FreeBSD ports (/usr/local/bin/hermes-agent); then PATH
    (hermes-agent, hermes). PY/SP are derived from the chosen bin when unset.
    missing='defaults' keeps snap path strings when nothing is found (import-safe);
    missing='die' exits with an actionable message (no snap on FreeBSD).
    """
    env = os.environ if environ is None else environ
    sysname = system if system is not None else os.uname().sysname

    bin_path = env.get("HERMES_BIN") or None
    py = env.get("HERMES_PY") or None
    sp = env.get("HERMES_SP") or None

    if not bin_path:
        # Linux snap when present; FreeBSD ports layout next; else PATH.
        if sysname != "FreeBSD" and exists(SNAP_BIN):
            bin_path = SNAP_BIN
        elif exists(FREEBSD_BIN):
            bin_path = FREEBSD_BIN
        elif exists(SNAP_BIN):
            bin_path = SNAP_BIN
        else:
            bin_path = which("hermes-agent") or which("hermes")

    if not bin_path:
        if missing == "die":
            die(
                "hermes-agent not found. Set HERMES_BIN to the CLI "
                "(FreeBSD: pkg install hermes-agent → /usr/local/bin/hermes-agent; "
                "lib at /usr/local/lib/hermes-agent — no snap). "
                "Elsewhere: curl installer (https://hermes-agent.nousresearch.com/install.sh) "
                "or a venv, then export HERMES_BIN."
            )
        bin_path, py, sp = SNAP_BIN, py or SNAP_PY, sp or SNAP_SP
        return bin_path, py, sp

    if not py:
        py = _derive_py(bin_path, exists=exists, which=which)
    if not sp:
        sp = _derive_sp(bin_path, py, exists=exists, run=run)
    if not sp:
        if missing == "die":
            die(
                f"could not locate hermes packages for {bin_path!r}. "
                "Set HERMES_SP to the directory that contains hermes_cli "
                "(FreeBSD ports: /usr/local/lib/hermes-agent) and HERMES_PY to that install's python."
            )
        sp = SNAP_SP if str(bin_path).startswith("/snap/bin/") else (FREEBSD_LIB if exists(FREEBSD_LIB) else SNAP_SP)

    if missing == "die" and not exists(bin_path):
        die(
            f"HERMES_BIN={bin_path!r} is missing. "
            "FreeBSD: pkg install hermes-agent (no snap). "
            "Or set HERMES_BIN to a real hermes-agent/hermes binary."
        )
    return bin_path, py, sp


def ensure_hermes():
    """Re-resolve with hard failure; update module globals for prefix/selftest/exec."""
    global HERMES_BIN, HERMES_PY, HERMES_SP
    HERMES_BIN, HERMES_PY, HERMES_SP = resolve_hermes(missing="die")
    return HERMES_BIN, HERMES_PY, HERMES_SP


HERMES_BIN, HERMES_PY, HERMES_SP = resolve_hermes(missing="defaults")
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
# Belt-and-suspenders for #85 prompt cache: upstream env_probe is process-lifetime only and
# pip detection can still flap across launches (cache miss / old installs without the overlay).
# Proper fix is the per-host cache in scripts/hermes_env_probe_cache/ (#96); keep cutting the
# stable prefix before this marker until that cache is proven on angel.
UNSTABLE_LINES = ("Python toolchain:",)   # same line as the small-host floor in docs/ram-safety.md
# Overlay dir prepended to PYTHONPATH for hermes-agent / HERMES_PY children (sitecustomize).
ENV_PROBE_CACHE_OVERLAY = os.path.join(ROOT, "scripts", "hermes_env_probe_cache")
AUX_TASKS = ["web_extract", "compression", "skills_hub", "approval", "mcp", "title_generation",
             "memory_query_rewrite", "tts_audio_tags", "triage_specifier", "kanban_decomposer",
             "profile_describer", "goal_judge", "curator", "monitor"]


def die(msg):
    print(f"hermes.sh: {msg}", file=sys.stderr); sys.exit(1)


CLIENTS = ("cli", "desktop", "webapp")


def client_argv(client, rest=None):
    """Hermes argv after HERMES_BIN for a frontend client surface.

    cli: pass-through rest (chat / TUI flags).
    desktop / webapp: prefix the upstream subcommand, then rest.
    """
    rest = list(rest or [])
    if client not in CLIENTS:
        die(f"--client must be one of {', '.join(CLIENTS)}, got {client!r}")
    if client == "cli":
        return rest
    return [client] + rest


def ensure_webapp_enabled(home):
    """Set webapp.enabled in the rendered HERMES_HOME config (idempotent)."""
    path = os.path.join(home, "config.yaml")
    cfg = {}
    if os.path.isfile(path):
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
    w = cfg.setdefault("webapp", {})
    if w.get("enabled") is True:
        return False
    w["enabled"] = True
    with open(path, "w") as f:
        f.write("# Generated by familia scripts/hermes_harness.py from graph.yaml. Do not edit.\n")
        yaml.safe_dump(cfg, f, sort_keys=False)
    return True


def require_client_subcommand(bin_path, client, *, run=subprocess.run, environ=None):
    """Refuse desktop/webapp when the resolved binary's --help does not list the subcommand.

    Skipped when FAMILIA_HERMES_CLIENT_PROBE=0 (unit tests / offline). cli never probes.
    """
    if client == "cli":
        return
    if os.environ.get("FAMILIA_HERMES_CLIENT_PROBE", "1") == "0":
        return
    env = hermes_child_env(environ=environ)
    try:
        r = run([bin_path, "--help"], capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        die(f"--client {client}: could not probe {bin_path!r}: {e}")
    text = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
    # Match a help token for the subcommand (word boundary-ish).
    token = client.lower()
    if re.search(rf"(?m)(?:^|\s){re.escape(token)}(?:\s|:|,|$)", text):
        return
    die(
        f"--client {client}: {bin_path} has no '{client}' subcommand "
        f"(upgrade hermes-agent / hermes, or use --client cli). "
        f"See docs/hermes-clients.md."
    )


def prepare_client_launch(home, client, rest, bin_path=None):
    """Apply webapp config if needed; return argv after HERMES_BIN."""
    bin_path = bin_path or HERMES_BIN
    require_client_subcommand(bin_path, client)
    if client == "webapp":
        if ensure_webapp_enabled(home):
            print("hermes.sh: webapp.enabled=true in HERMES_HOME config", file=sys.stderr)
    argv = client_argv(client, rest)
    print(f"hermes.sh: client={client} argv0={argv[0] if argv else '(chat/cli)'}", file=sys.stderr)
    return argv


def hermes_child_env(extra=None, environ=None):
    """Env for hermes-agent / HERMES_PY children: #96 host-cache overlay on PYTHONPATH.

    Prepends scripts/hermes_env_probe_cache so sitecustomize wraps tools.env_probe across
    process launches. HERMES_SP still works (children insert it on sys.path themselves).
    Force a fresh probe with FAMILIA_HERMES_ENV_PROBE_REFRESH=1.
    When HERMES_HOME/bin exists (Agent-Reach wrapper from link_reaches), prepend it to PATH.
    """
    env = dict(os.environ if environ is None else environ)
    if extra:
        env.update(extra)
    overlay = ENV_PROBE_CACHE_OVERLAY
    if os.path.isdir(overlay):
        parts = [p for p in (env.get("PYTHONPATH") or "").split(os.pathsep) if p]
        if overlay not in parts:
            env["PYTHONPATH"] = os.pathsep.join([overlay] + parts)
    home = env.get("HERMES_HOME")
    if home:
        bindir = os.path.join(home, "bin")
        if os.path.isdir(bindir):
            path_parts = [p for p in (env.get("PATH") or "").split(os.pathsep) if p]
            if bindir not in path_parts:
                env["PATH"] = os.pathsep.join([bindir] + path_parts)
    return env


def strip_secrets(v):
    if isinstance(v, dict):
        return {k: strip_secrets(x) for k, x in v.items() if not SECRET_RE.search(str(k))}
    if isinstance(v, list):
        return [strip_secrets(x) for x in v]
    return v


def load_graph(path, check_files=True, host=None):
    """Load + validate. check_files/host match validate_graph (angel must not need box GGUFs)."""
    g = yaml.safe_load(open(path)); g["_path"] = path
    errs, _ = vg.validate(g, check_files=check_files, host=host)
    for e in errs: print(f"graph: ERROR: {e}", file=sys.stderr)
    if errs: die("graph validation failed; not launching")
    return g


def local_graph_host(g):
    """Graph host id for this machine via hosts.*.local_names / hostname, or None."""
    try:
        from hostname_pin import resolve_candidate
        here = resolve_candidate()
    except ImportError:
        here = __import__("socket").gethostname().split(".")[0]
    hosts = g.get("hosts") or {}
    if here in hosts:
        return here
    for hid, h in hosts.items():
        names = h.get("local_names") or []
        if here in names or __import__("socket").gethostname() in names:
            return hid
    return None


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


def lean_toolsets(cfg, keep=()):
    """Only ever narrows user toolsets; `keep` (graph-declared MCP toolsets) always survives."""
    have = ((cfg.get("platform_toolsets") or {}).get("cli"))
    out = [t for t in have if t in LEAN_TOOLSETS] if isinstance(have, list) else list(LEAN_TOOLSETS)
    return out + [t for t in keep if t not in out]


def mcp_servers(a):
    """agents.<a>.mcp -> hermes mcp_servers. Secrets are written as ${VAR} refs that hermes-agent
    interpolates at load (tools/mcp_tool_config.py); no secret value ever lands in config.yaml."""
    out = {}
    for srv, c in (a.get("mcp") or {}).items():
        if c.get("enabled") is False: continue
        e = {k: c[k] for k in ("command", "args", "url", "tools") if k in c}
        env_from = c.get("env_from") or []
        env_from = list(env_from.values()) if isinstance(env_from, dict) else list(env_from)
        if env_from: e["env"] = {v: "${" + v + "}" for v in env_from}
        if c.get("headers_from"): e["headers"] = {h: "Bearer ${" + v + "}" if h.lower() == "authorization"
                                                  else "${" + v + "}" for h, v in c["headers_from"].items()}
        out[srv] = e
    return out


def mcp_env_allowlist(a):
    """Env var names declared by this agent's MCP servers (the only secrets passed to hermes)."""
    names = []
    for c in (a.get("mcp") or {}).values():
        if not isinstance(c, dict) or c.get("enabled") is False: continue
        for k in ("env_from", "headers_from"):
            v = c.get(k) or []
            names += list(v.values()) if isinstance(v, dict) else list(v)
    return sorted(set(names))



def link_reaches(g, agent_name, home):
    """When the agent is listed under reaches.*.agents, link Agent-Reach into HERMES_HOME.

    Symlinks the pinned skill and writes bin/agent-reach (CLI via PYTHONPATH to the
    pin checkout). Never copies the repo; never installs from the network. Reach
    tools still go through the terminal/MCP approval gate — not pasted into
    llama-server (DESIGN.md).
    """
    try:
        import familia_agent_reach as ar
    except ImportError:
        return []
    if not ar.reaches_for(g, agent_name):
        return []
    return ar.link_reach_into_home(home)


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



# ---- tool routing (Brian 2026-10-31): Hermes side of CFG-SPEC-TOOLS-007..010 (#243).
# Capability / explicit one-hop route / server tool policy live in validate_graph
# (tool_capable, tool_route, tool_policy) — do not reimplement them here. This module only
# decides where a Hermes agent sends tool-driving turns, and keeps guardian/pentest/defender
# closed for Hermes MCP/toolsets (docs/config/pentest-policy.md, CFG-PENT-POL-004).
#
# Order in route_tools:
#   1. tool_free → none (Hermes seatbelt; #243 fail-closed TYPEs plus name/role heuristics)
#   2. vg.tool_capable → direct
#   3. vg.tool_route (explicit nodes.<n>.tool_route, one hop, never fail-closed) → nexus
#   4. same-host then ssh-nexus mesh discovery (NOT in #243; Hermes-only fallback)
#
# TODO(pentest-policy): when graph_types accepts `pentests.<p>.policy` (today
# tests/test_config_spec.py strict-xfails until then) AND hermes-agent can enforce
# per-action confirmation on *every* tool call (today `approvals.mode: manual|smart`
# only gates dangerous shell / execute_code, not every MCP/toolset call), open tools
# for mode `tools-confirm` (and `autonomous-lab`) via pentest_tools_allowed() below:
#   - route_tools → mode=direct on the pentest node
#   - render sets approvals.mode=manual (no yolo / mode=off)
#   - tools = full set (platform toolsets + declared MCP) per CFG-PENT-MODE-004
# slash-confirm stays tools=none (CFG-PENT-MODE-003 advisory chat). Until then keep
# closed: tool_free always, never open by default. See tests/test_hermes_tool_routing.py
# xfail(strict=True) for the expected tools-confirm path.
# Modes that the SPEC says may carry tools (once preconditions + per-action confirm land).
PENTEST_TOOLS_MODES = frozenset({"tools-confirm", "autonomous-lab"})


def _node_role(g, name):
    """Roles for Hermes seatbelt. Broader than vg.node_type: also name-based defender and
    node_role.infer_role, so tests/aliases that stamp defender only in the node name still close."""
    from node_role import infer_role
    n = g["nodes"][name]
    raw = {n.get("role"), ((g.get("models") or {}).get(n.get("model")) or {}).get("role"),
           vg.node_type(g, name), infer_role(name, n, g)}
    if name.endswith("-defender") or name == "defender":
        raw.add("defender")
    return {r for r in raw if r}


def pentest_for_node(g, name):
    """First pentests.* entry whose `node` is `name`, or None. Forward-compat for policy mode."""
    for p in (g.get("pentests") or {}).values():
        if isinstance(p, dict) and p.get("node") == name:
            return p
    return None


def pentest_policy_mode(g, name):
    """Read pentests.<p>.policy.mode when present. graph_types does not accept `policy` yet
    (CFG-PENT-* SPEC); returns None until an overlay / future schema carries it."""
    p = pentest_for_node(g, name)
    if not p:
        return None
    pol = p.get("policy")
    if not isinstance(pol, dict):
        return None
    mode = pol.get("mode")
    return mode if isinstance(mode, str) else None


def pentest_tools_allowed(g, name):
    """Would the pentest-policy ladder grant tools on this node?
    Closed today: always False. See TODO(pentest-policy) above — gate on
    pentest_policy_mode in PENTEST_TOOLS_MODES plus per-action confirm wiring."""
    _ = pentest_policy_mode(g, name)
    return False


def tool_free(g, name):
    """Guardian / pentest / defender: no Hermes tools (incl. MCP) by default.
    Aligns with vg.FAIL_CLOSED_TYPES; future tools-confirm opt-in via pentest_tools_allowed."""
    if not (_node_role(g, name) & set(vg.FAIL_CLOSED_TYPES)):
        return False
    if pentest_tools_allowed(g, name):
        return False
    return True


def tool_capable(g, name):
    """Hermes view: vg.tool_capable (nodes.*.tool_capable > models.*.tool_calls > TYPE) and
    not tool_free. Do not re-read the fields here — #243 owns that."""
    if tool_free(g, name):
        return False
    return vg.tool_capable(g, name)


def nexus_meshes(g, host):
    """ssh nexus meshes (meshes.*, type ssh) that `host` is a member of."""
    return [k for k, m in (g.get("meshes") or {}).items()
            if (m or {}).get("type") == "ssh" and host in ((m or {}).get("members") or [])]


def _discovery_ok(g, src, k):
    """Same-host / mesh fallback candidate: active, not self, not fail-closed, capable per #243."""
    o = (g.get("nodes") or {}).get(k) or {}
    return (k != src and o.get("status") != "planned"
            and not tool_free(g, k) and vg.tool_capable(g, k))


def route_tools(g, agent):
    """-> {"mode": none|direct|nexus, "node", "via"}.
    Reuses validate_graph.tool_capable / tool_route / tool_policy (#243). Explicit
    nodes.<n>.tool_route wins as the nexus target; same-host then mesh discovery is the
    Hermes-only fallback when #243 has no route. Never into guardian/pentest/defender."""
    _, name, n, _ = node_for(g, agent)
    if tool_free(g, name):
        return {"mode": "none", "node": None, "via": None, "reason": "tool-free node"}
    if vg.tool_capable(g, name):
        # Direct: model emits tool calls; Hermes runs MCP/toolsets locally. tool_policy is the
        # llama-server --tools grant (separate layer); do not require it for Hermes direct.
        return {"mode": "direct", "node": name, "via": None}
    # Explicit one-hop from graph (#243). tool_route already rejects fail-closed / routed targets.
    t = vg.tool_route(g, name)
    if t and not tool_free(g, t):
        return {"mode": "nexus", "node": t, "via": None, "reason": "tool_route"}
    # #243 does not discover a target — Hermes falls back to same-host, then ssh nexus mesh.
    host = n.get("host")
    nodes = g.get("nodes") or {}
    for k in sorted(nodes):
        if nodes[k].get("host") == host and _discovery_ok(g, name, k):
            return {"mode": "nexus", "node": k, "via": None}
    for mesh in nexus_meshes(g, host):
        peers = set(g["meshes"][mesh].get("members") or []) - {host}
        for k in sorted(nodes):
            if nodes[k].get("host") in peers and _discovery_ok(g, name, k):
                return {"mode": "nexus", "node": k, "via": mesh}
    return {"mode": "none", "node": None, "via": None, "reason": "no tool-capable node reachable"}


def node_base(g, k, from_host):
    """OpenAI base URL for node k as seen from from_host (loopback bind only works same-host)."""
    n = g["nodes"][k]; b = bind(n)
    if n.get("host") != from_host and (b in ("localhost", "::1") or str(b).startswith("127.")):
        b = ((g.get("hosts") or {}).get(n.get("host")) or {}).get("addr") or b
    return f"http://{b}:{n['port']}/v1"


def apply_tool_route(g, agent, cfg, route):
    if route["mode"] == "none":
        cfg.pop("mcp_servers", None)
        cfg["platform_toolsets"] = dict(cfg.get("platform_toolsets") or {}, cli=[])
    elif route["mode"] == "nexus":
        _, _, n, _ = node_for(g, agent)
        cfg["model"] = dict(cfg["model"], base_url=node_base(g, route["node"], n.get("host")), default=route["node"])
    # TODO(pentest-policy): when pentest_tools_allowed opens tools-confirm, force
    # approvals.mode=manual here (never off / yolo) so each dangerous action still
    # prompts. Full per-tool confirm still needs hermes-agent support beyond
    # dangerous-shell gating — see docs/config/pentest-policy.md CFG-PENT-MODE-004.
    _, name, _, _ = node_for(g, agent)
    if route["mode"] != "none" and pentest_tools_allowed(g, name):
        appr = dict(cfg.get("approvals") or {})
        appr["mode"] = "manual"
        cfg["approvals"] = appr
    return cfg


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
                    "context_length": ctx, "api_key": familia_auth.api_key() or "local"}
    cfg["compression"] = {"enabled": True,
                          "threshold": comp.get("threshold", 0.75),
                          "target_ratio": comp.get("target_ratio", 0.20),
                          "protect_first_n": comp.get("protect_first_n", 3),
                          "protect_last_n": comp.get("protect_last_n", 8)}
    ag = cfg.setdefault("agent", {})
    ag["disabled_toolsets"] = [t for t in ag.get("disabled_toolsets", []) or [] if t != "context_engine"]
    aux = {"transient_retries": 2}
    for t in AUX_TASKS:
        aux[t] = {"provider": "custom", "model": alias, "base_url": base, "api_key": familia_auth.api_key() or "local",
                  "timeout": comp.get("aux_timeout", 3600)}
    cfg["auxiliary"] = aux
    declared = mcp_servers(a)
    if declared:  # graph-declared MCP wins over a same-named user entry (whose secrets were stripped)
        cfg["mcp_servers"] = dict(cfg.get("mcp_servers") or {}, **declared)
    if prompt_profile(g, a, n) == "lean":
        cfg["platform_toolsets"] = dict(cfg.get("platform_toolsets") or {},
                                        cli=lean_toolsets(cfg, keep=[f"mcp-{k}" for k in declared]))
        aux = cfg.get("auxiliary") or {}
        for t in LEAN_AUX_DROP:
            aux.pop(t, None)
        cfg["auxiliary"] = aux
    apply_tool_route(g, agent, cfg, route_tools(g, agent))
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
    link_reaches(g, agent, home)
    return home, base, n, name


def props(n):
    url = f"http://{bind(n)}:{n['port']}/props"
    try:
        with familia_auth.open_url(url, timeout=5) as r:
            return json.load(r)
    except Exception:
        return None


def tools_live(n, timeout=5):
    """True when llama-server Server Tools are enabled (GET /tools not 403/feature_disabled).

    Graph `server_tools` only affects argv at launch; a crash/restart without `--tools`
    still answers /props with the right n_ctx. Refuse to adopt that process (L-server-tools).
    """
    url = f"http://{bind(n)}:{n['port']}/tools"
    try:
        with familia_auth.open_url(url, timeout=timeout) as r:
            body = r.read(512).decode("utf-8", "replace")
            if "feature_disabled" in body:
                return False
            return 200 <= getattr(r, "status", 200) < 400
    except urllib.error.HTTPError as e:
        try:
            body = e.read(512).decode("utf-8", "replace")
        except Exception:
            body = ""
        if e.code == 403 or "feature_disabled" in body:
            return False
        return False
    except Exception:
        return False


def _wants_server_tools(n):
    st = n.get("server_tools")
    return st == "all" or (isinstance(st, list) and bool(st))


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
    """Adopt a live node only — never daemon-spawn llama-server (non-screen forbidden).

    timeout is kept for API compatibility; cold start wait was removed with auto-spawn.
    """
    want = n["ctx"] // n["parallel"]
    p = props(n)
    if p is None:
        die(
            f"node {name} is not up on {bind(n)}:{n['port']}. "
            f"Start it under DETACH_MODE=screen-attached "
            f"(e.g. DETACH_MODE=screen-attached sh scripts/serve.sh {name} "
            f"or DETACH_MODE=screen-attached ./start.sh --host <graph-host>). "
            f"hermes_harness will not daemon-spawn llama-server."
        )
    got = (p.get("default_generation_settings") or {}).get("n_ctx")
    if got != want:
        die(f"node {name} on port {n['port']} reports n_ctx {got}, graph expects per-slot {want}; "
            "something else is on that port or it was started with other args")
    if _wants_server_tools(n) and not tools_live(n):
        die(
            f"node {name} on port {n['port']} is up but Server Tools are disabled "
            f"(/tools 403 feature_disabled or unreachable). "
            f"Graph has server_tools={n.get('server_tools')!r}; restart via "
            f"DETACH_MODE=screen-attached so validate_graph emits --tools … "
            f"(L-server-tools / known-issues M0)."
        )
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
    hermes is asked inside its own snap environment (outside it, fewer tools are detected);
    non-snap uses HERMES_PY + HERMES_SP from resolve_hermes()."""
    env = hermes_child_env({"HERMES_HOME": home, "HERMES_SP": HERMES_SP, "FAMILIA_PREFIX_CHILD": PREFIX_CHILD})
    if HERMES_BIN.startswith("/snap/bin/"):
        cmd = ["snap", "run", "--shell", os.path.basename(HERMES_BIN), "-c", '"$SNAP/bin/python3" -c "$FAMILIA_PREFIX_CHILD"']
    else:
        cmd = [HERMES_PY, "-c", PREFIX_CHILD]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:])
    return json.loads(r.stdout)


def mem_available_mib():
    """Best-effort free RAM in MiB (Linux MemAvailable; FreeBSD free pages). None if unknown."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["sysctl", "-n", "vm.stats.vm.v_free_count", "hw.pagesize"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            parts = [p for p in r.stdout.split() if p.strip()]
            if len(parts) >= 2:
                return (int(parts[0]) * int(parts[1])) // (1024 * 1024)
    except Exception:
        pass
    return None


def warm_prompt(g, name, n, home):
    """Nodes with slot_save: restore the fixed prompt prefix from disk, or prefill and save it once
    (scripts/prompt_cache.py, #85). Best effort: any failure only means a slower first turn.

    Under low MemAvailable (default floor 2048 MiB, FAMILIA_WARM_MIN_AVAIL_MIB) skip entirely so
    angel 64K mmap+spill cannot hang the sole-worker host in a multi-hour prefill. Prefill timeout
    defaults to 600s (FAMILIA_WARM_TIMEOUT); restore path stays short inside prompt_cache.warm.
    """
    if not (n.get("slot_save") or n.get("spill_path")):
        return None
    min_avail = int(os.environ.get("FAMILIA_WARM_MIN_AVAIL_MIB", "2048"))
    avail = mem_available_mib()
    if avail is not None and avail < min_avail:
        print(
            f"hermes.sh: prompt cache skipped (MemAvailable {avail} MiB < {min_avail}; "
            f"avoid 64K mmap/swap hang)",
            file=sys.stderr,
        )
        return None
    import prompt_cache
    base = f"http://{bind(n)}:{n['port']}"
    warm_timeout = int(os.environ.get("FAMILIA_WARM_TIMEOUT", "600"))
    try:
        d = hermes_prefix(home)
        text = prompt_cache.stable_prefix(base, d["system"], d["tools"], d.get("volatile", ""), unstable=UNSTABLE_LINES)
        return prompt_cache.warm(
            base, prompt_cache.prefix_tokens(base, text), tag=name, timeout=warm_timeout,
        )[0]
    except Exception as e:
        print(f"hermes.sh: prompt cache skipped ({e})", file=sys.stderr)
        return None


def chat(base, alias, messages, max_tokens=400):
    body = json.dumps({"model": alias, "messages": messages, "max_tokens": max_tokens,
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = familia_auth.request(base + "/chat/completions", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=7200) as r:
        return json.load(r)["choices"][0]["message"].get("content") or ""


SELFTEST_CHILD = r'''
import json, os, sys
sys.path.insert(0, os.environ["HERMES_SP"])
from agent.context_compressor import ContextCompressor
spec = json.load(sys.stdin)
cc = ContextCompressor(model=spec["alias"], threshold_percent=0.75, protect_first_n=1,
                       protect_last_n=2, summary_target_ratio=spec["target_ratio"], quiet_mode=True,
                       base_url=spec["base"], api_key=spec.get("api_key") or "local", config_context_length=spec["ctx"],
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
    spec = {"alias": alias, "base": base, "ctx": ctx, "target_ratio": 0.02, "messages": msgs,
            "api_key": familia_auth.api_key()}  # via stdin, not env/argv
    env = hermes_child_env({"HERMES_HOME": home, "HERMES_SP": HERMES_SP})
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


def run_escalating(g, agent, light, swap_back, rest, client="cli"):
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
    argv = prepare_client_launch(home, client, rest)
    return subprocess.call([HERMES_BIN] + argv, env=hermes_child_env({"HERMES_HOME": home}),
                           preexec_fn=oom_adj.preexec())


USAGE = __doc__.split("usage: ", 1)[1].strip()


def parse_argv(argv):
    """-> (agent, graph_path, mode, light, swap_back, client, rest). SystemExit(0) for --help,
    SystemExit(2) for an unknown argument or a missing value."""
    agent, graph_path, rest = "hermes", os.path.join(ROOT, "graph.yaml"), []
    mode, light, swap_back, client = "run", None, True, "cli"
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
        elif x == "--client":
            client = val(x)
            if client not in CLIENTS:
                print(f"hermes_harness.py: --client must be one of {', '.join(CLIENTS)}, got {client!r}\nusage: {USAGE}", file=sys.stderr)
                raise SystemExit(2)
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
    if mode != "run" and mode != "escalate" and client != "cli":
        print(f"hermes_harness.py: --client only applies to a live launch (not --render-only / --selftest-compaction)\nusage: {USAGE}", file=sys.stderr)
        raise SystemExit(2)
    return agent, graph_path, mode, light, swap_back, client, rest


def main(argv):
    agent, graph_path, mode, light, swap_back, client, rest = parse_argv(argv)
    # Peek hosts for scoped file checks before full validate (other hosts' GGUFs stay optional).
    peek = yaml.safe_load(open(graph_path)) or {}
    peek["_path"] = graph_path
    scope = local_graph_host(peek)
    # --render-only: schema only (no weight files). Run/selftest: files for this host only.
    g = load_graph(graph_path, check_files=(mode != "render"), host=scope if mode != "render" else None)
    if mode == "render":
        home, base, n, name = render(g, agent)
        print(f"hermes.sh: HERMES_HOME={home} model={base}", file=sys.stderr)
        return 0
    ensure_hermes()
    if mode == "selftest":
        return selftest(g, agent)
    home, base, n, name = render(g, agent)
    print(f"hermes.sh: HERMES_HOME={home} model={base} bin={HERMES_BIN}", file=sys.stderr)
    if mode == "escalate":
        return run_escalating(g, agent, light or name, swap_back, rest, client=client)
    ensure_server(g, name, n)
    warm_prompt(g, name, n, home)
    argv = prepare_client_launch(home, client, rest)
    launch_env = hermes_child_env({"HERMES_HOME": home})
    os.environ.clear()
    os.environ.update(launch_env)
    # #112: hermes process is first-to-kill (no longer Popen's llama-server; serve.sh does)
    oom_adj.set_self()
    os.execv(HERMES_BIN, [HERMES_BIN] + argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
