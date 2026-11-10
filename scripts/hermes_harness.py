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
HERMES_EXEC = None   # trusted realpath of HERMES_BIN, set by ensure_hermes(); what is exec'd
# pip / uv / install.sh layouts ship two console scripts: `hermes` (hermes_cli.main, the full CLI
# with -z, -t, desktop, webapp) and `hermes-agent` (agent.legacy_cli, a single-query runner that
# has none of those). Seen in every upstream release from v0.21.7 through v0.22.6.
LEGACY_RUNNER_MARK = b"agent.legacy_cli"


def _path_exists(p):
    return bool(p) and os.path.exists(p)


def _shebang_parts(path):
    """Split #! tokens from *path*, or None."""
    try:
        with open(path, "rb") as f:
            line = f.readline(256)
    except OSError:
        return None
    if not line.startswith(b"#!"):
        return None
    parts = line[2:].decode("utf-8", "replace").strip().split()
    return parts or None


def _is_env_shebang(path):
    """True when *path*'s shebang is `#!/usr/bin/env CMD` (or any `env CMD`)."""
    parts = _shebang_parts(path)
    return bool(parts) and os.path.basename(parts[0]) == "env" and len(parts) >= 2


def _read_shebang(path, path_env=None):
    """Return interpreter from a #! line, or None.

    For `#!/usr/bin/env CMD`, resolve CMD on *path_env* (a PATH string) when given, else the
    process PATH (Boundary N1a: launch must re-resolve against the child's PATH, which prepends
    HERMES_HOME/bin).
    """
    parts = _shebang_parts(path)
    if not parts:
        return None
    if os.path.basename(parts[0]) == "env" and len(parts) >= 2:
        return shutil.which(parts[1], path=path_env) or parts[1]
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


def _is_legacy_runner(path, exists=_path_exists):
    """True when *path* is upstream's legacy single-query console script (agent.legacy_cli)."""
    if not path or str(path).startswith("/snap/bin/") or not exists(path):
        return False
    try:
        with open(path, "rb") as f:
            return LEGACY_RUNNER_MARK in f.read(4096)
    except OSError:
        return False


def _private_group(gid):
    """True when *gid* is this user's own primary group with the user's name (user-private group)."""
    try:
        import grp, pwd
        return gid == os.getegid() and grp.getgrgid(gid).gr_name == pwd.getpwuid(os.geteuid()).pw_name
    except (ImportError, KeyError):
        return False


def _node_problem(p, st, is_dir):
    """Owner must be root or this user; no group/other write, except a root-owned sticky directory
    (/tmp) or a user-private group."""
    import stat
    if st.st_uid not in (0, os.geteuid()):
        return f"{p} is owned by uid {st.st_uid}"
    sticky_root = is_dir and st.st_mode & stat.S_ISVTX and st.st_uid == 0
    if st.st_mode & stat.S_IWOTH and not sticky_root:
        return f"{p} is world-writable"
    if st.st_mode & stat.S_IWGRP and not sticky_root and not _private_group(st.st_gid):
        return f"{p} is group-writable"
    return None


def _dirs_problem(path):
    """Every directory from dirname(path) up to / must pass _node_problem (a symlinked directory
    component is checked for its owner only; its own mode bits mean nothing)."""
    import stat
    d = os.path.dirname(path)
    while True:
        try:
            st = os.lstat(d)
        except OSError as e:
            return f"cannot stat {d} ({e.strerror or e})"
        if stat.S_ISLNK(st.st_mode):
            if st.st_uid not in (0, os.geteuid()):
                return f"{d} is owned by uid {st.st_uid}"
        else:
            why = _node_problem(d, st, True)
            if why:
                return why
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def trust_exec(path, *, interpreter=True, path_env=None):
    """(realpath, None) when *path* is safe to exec, else (realpath or None, reason). realpath once:
    the real file must be regular, executable, owned by root or this user, not group/other
    writable (user-private group excepted); every parent of both the given path and the realpath
    likewise; a '#!' interpreter (venv python, /bin/sh, /usr/bin/env) gets the same check. Callers
    exec the returned realpath (HERMES_EXEC), so nothing outside root's and the user's control can
    swap the binary between this check and the exec. *path_env* is the PATH used to resolve an
    `env` shebang (Boundary N1a: pass the child PATH with HERMES_HOME/bin prepended at launch)."""
    import stat
    if not path or not os.path.isabs(str(path)):
        return None, "not an absolute path"
    path = os.path.normpath(str(path))
    real = os.path.realpath(path)
    try:
        st = os.stat(real)
    except OSError as e:
        return real, f"cannot stat ({e.strerror or e})"
    if not stat.S_ISREG(st.st_mode):
        return real, "not a regular file"
    if not os.access(real, os.X_OK):
        return real, "not executable"
    why = _node_problem(real, st, False) or _dirs_problem(path) or (real != path and _dirs_problem(real))
    if why:
        return real, why
    if interpreter:
        interp = _read_shebang(real, path_env=path_env)
        if interp and os.path.isabs(interp):
            _r, why = trust_exec(interp, interpreter=False)
            if why:
                return real, f"its interpreter {interp}: {why}"
    return real, None


def exec_problem(path):
    """Why *path* must not be exec'd as hermes (see trust_exec), or None."""
    return trust_exec(path)[1]


def _full_cli_for(bin_path, exists=_path_exists, check=exec_problem):
    """The full `hermes` CLI next to a legacy `hermes-agent` script, else bin_path unchanged. The
    sibling is only taken when it passes exec_problem (absolute, regular, executable, not o+w)."""
    if not _is_legacy_runner(bin_path, exists=exists):
        return bin_path
    sibling = os.path.join(os.path.dirname(os.path.abspath(bin_path)), "hermes")
    if not exists(sibling) or _is_legacy_runner(sibling, exists=exists):
        return bin_path
    why = check(sibling)
    if why:
        print(f"hermes.sh: warning: not using {sibling} ({why}); keeping {bin_path}", file=sys.stderr)
        return bin_path
    return sibling


def _snap_sp(exists=_path_exists):
    """Snap site-packages for whatever python the snap ships (upstream runs on 3.14 now; the
    snap was 3.12). Highest python3.N first; SNAP_SP when nothing else exists."""
    def key(p):
        m = re.search(r"python3\.(\d+)", p)
        return int(m.group(1)) if m else -1
    found = sorted(glob.glob("/snap/hermes-agent/current/lib/python3.*/site-packages"), key=key, reverse=True)
    for cand in found + [SNAP_SP]:
        if exists(cand):
            return cand
    return SNAP_SP


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


def _no_run(*a, **k):
    """Stand-in for subprocess.run when HERMES_PY failed trust_exec: never execute it."""
    raise OSError("untrusted HERMES_PY not executed")


def _derive_sp(bin_path, py, exists=_path_exists, run=subprocess.run):
    if bin_path and str(bin_path).startswith("/snap/bin/"):
        return _snap_sp(exists=exists)
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
                   system=None, run=subprocess.run, missing="defaults", check=exec_problem):
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
            bin_path = _full_cli_for(bin_path, exists=exists, check=check)

    if not bin_path:
        if missing == "die":
            die(
                "hermes-agent not found. Set HERMES_BIN to the CLI "
                "(FreeBSD: pkg install hermes-agent → /usr/local/bin/hermes-agent; "
                "lib at /usr/local/lib/hermes-agent — no snap). "
                "Elsewhere: upstream install.sh at the pinned commit (python3 scripts/hermes_pin.py check prints it) "
                "or a venv, then export HERMES_BIN."
            )
        bin_path, py, sp = SNAP_BIN, py or SNAP_PY, sp or SNAP_SP
        return bin_path, py, sp

    if not py:
        py = _derive_py(bin_path, exists=exists, which=which)
    # HERMES_PY is executed (site-packages probe below, toolchain check, selftest/prefix children):
    # same trust rules as HERMES_BIN (Boundary N1). Launch refuses; import-time resolution only
    # skips the probe. The snap's python runs inside the snap's own read-only squashfs.
    py_why = None if str(bin_path).startswith("/snap/bin/") else check(py)
    if not sp:
        sp = _derive_sp(bin_path, py, exists=exists, run=run if not py_why else _no_run)
    if not sp:
        if missing == "die":
            die(
                f"could not locate hermes packages for {bin_path!r}. "
                "Set HERMES_SP to the directory that contains hermes_cli "
                "(FreeBSD ports: /usr/local/lib/hermes-agent) and HERMES_PY to that install's python."
            )
        sp = _snap_sp(exists=exists) if str(bin_path).startswith("/snap/bin/") else (FREEBSD_LIB if exists(FREEBSD_LIB) else SNAP_SP)

    if missing == "die" and not exists(bin_path):
        die(
            f"HERMES_BIN={bin_path!r} is missing. "
            "FreeBSD: pkg install hermes-agent (no snap). "
            "Or set HERMES_BIN to a real hermes-agent/hermes binary."
        )
    if missing == "die":
        why = check(bin_path)
        if why:
            src = "HERMES_BIN" if env.get("HERMES_BIN") else "hermes"
            die(f"{src}={bin_path!r}: {why}; refusing to launch it. Point HERMES_BIN at an absolute "
                "path to the hermes CLI: a regular, executable file owned by root or you, not group/"
                "world-writable, in directories only root or you can write.")
        if py_why:
            src = "HERMES_PY" if env.get("HERMES_PY") else "derived HERMES_PY"
            die(f"{src}={py!r}: {py_why}; refusing to run it (same rules as HERMES_BIN).")
    if missing == "die" and _is_legacy_runner(bin_path, exists=exists):
        print(f"hermes.sh: warning: {bin_path} is hermes-agent's legacy single-query runner "
              "(no -z/-t/desktop/webapp); point HERMES_BIN at the `hermes` CLI of the same install",
              file=sys.stderr)
    return bin_path, py, sp


def _py_version(py, run=subprocess.run):
    """(major, minor) of interpreter *py*, or None when it cannot be asked."""
    try:
        r = run([py, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.fullmatch(r"(\d+)\.(\d+)", (r.stdout or "").strip()) if r.returncode == 0 else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def check_toolchain(bin_path, py, *, run=subprocess.run, environ=None):
    """Warn when HERMES_PY is older than the pinned hermes' python floor (config/hermes-agent.pins.json:
    upstream declares its dependencies only for 3.14+). FAMILIA_HERMES_PIN_CHECK=1 also compares
    `hermes --version` with the channel's pin (offline; =strict refuses a mismatch).
    FAMILIA_HERMES_TOOLCHAIN_CHECK=0 skips everything. Returns a list of warnings."""
    env = os.environ if environ is None else environ
    if env.get("FAMILIA_HERMES_TOOLCHAIN_CHECK", "1") == "0":
        return []
    import hermes_pin
    try:
        want = hermes_pin.resolve_ref(offline=True, environ=env)
    except (hermes_pin.PinError, OSError, ValueError) as e:
        die(f"hermes pin: {e}")
    warns = []
    floor = tuple(int(x) for x in str(want.get("python") or "0.0").split(".")[:2])
    have = None if str(bin_path).startswith("/snap/bin/") else _py_version(py, run=run)
    if have and have < floor:
        warns.append(f"HERMES_PY {py} is python {have[0]}.{have[1]}; hermes-agent {want['ref']} needs "
                     f">= {floor[0]}.{floor[1]} (upstream declares its dependencies only for 3.14+)")
    mode = env.get("FAMILIA_HERMES_PIN_CHECK", "0")
    if mode in ("1", "strict"):
        ver, commit = hermes_pin.installed_version(bin_path, run=run, env=hermes_child_env(environ=env))
        if not hermes_pin.matches(want, ver, commit):
            msg = (f"installed hermes {ver or 'unknown'} ({commit or '?'}) is not the {want['channel']} pin "
                   f"{want['ref']} ({(want.get('commit') or '?')[:12]}); "
                   f"to install it: {hermes_pin.install_hint(want, bin_path)}")
            if mode == "strict":
                die(msg)
            warns.append(msg)
    for w in warns:
        print(f"hermes.sh: warning: {w}", file=sys.stderr)
    return warns


def ensure_hermes():
    """Re-resolve with hard failure; update module globals for prefix/selftest/exec."""
    global HERMES_BIN, HERMES_PY, HERMES_SP, HERMES_EXEC
    HERMES_BIN, HERMES_PY, HERMES_SP = resolve_hermes(missing="die")
    real, why = trust_exec(HERMES_BIN)
    if why:
        die(f"hermes {HERMES_BIN!r}: {why}; refusing to launch it")
    HERMES_EXEC = real   # exec this realpath; argv[0] stays HERMES_BIN (snap dispatches on argv[0])
    check_toolchain(HERMES_BIN, HERMES_PY)
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
             "profile_describer", "goal_judge", "curator", "monitor",
             # Text aux tasks upstream added (v0.22.x) that otherwise default to provider "auto":
             "review", "background_review"]
# Modality / multi-model aux tasks. Upstream's "auto" for these walks a cloud provider chain (vision)
# or the built-in MoA preset (openai-codex / openrouter), so prompt content could leave the box when a
# cloud key is set. Unless FAMILIA_HERMES_ALLOW_CLOUD=1 they are pinned to the local node (a node
# without vision/voice fails locally instead of falling through to a cloud provider) and MoA is
# disabled with a local-only preset. See docs/hermes-pin.md.
MODAL_AUX_TASKS = ("vision", "voice_chat", "moa_reference", "moa_aggregator")
ALLOW_CLOUD_ENV = "FAMILIA_HERMES_ALLOW_CLOUD"
# Cloud LLM credentials scrubbed from every hermes child env unless FAMILIA_HERMES_ALLOW_CLOUD=1:
# any *_API_KEY / *_API_TOKEN (FAMILIA_* kept) plus these. MCP secrets the graph declares
# (agents.<a>.mcp env_from / headers_from, see mcp_env_allowlist) are always kept.
CLOUD_KEY_RE = re.compile(r"^(?!FAMILIA_)[A-Za-z0-9_]*_API_(?:KEY|TOKEN)$")
# Static superset (Boundary B3), used with or without an upstream tree: provider env names upstream
# hermes-agent v0.22.6 registers (PROVIDER_REGISTRY api_key_env_vars incl. plugin providers) that the
# regex above misses, OAuth/bearer tokens, and GCP/Vertex/HF credentials. Every AWS_* name is also
# dropped (boto chain: keys, AWS_PROFILE, AWS_CONFIG_FILE, AWS_SHARED_CREDENTIALS_FILE, web identity...).
CLOUD_KEY_NAMES = frozenset({
    "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "AZURE_OPENAI_AD_TOKEN", "AWS_BEARER_TOKEN_BEDROCK",
    "GOOGLE_APPLICATION_CREDENTIALS", "VERTEX_CREDENTIALS_PATH", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN",
    "QWEN_API_KEY", "NOUS_API_KEY", "OPENAI_ORG_ID", "OPENAI_ORGANIZATION", "OPENAI_BASE_URL",
    "OPENAI_API_BASE", "ANTHROPIC_BASE_URL", "CODEX_HOME", "CLOUDSDK_CONFIG"})
CLOUD_KEY_PREFIXES = ("AWS_",)
# hermes-agent v0.22.6 PROVIDER_REGISTRY api_key_env_vars (plugin providers included), for hosts
# where no hermes source tree is found; upstream_provider_env_names() adds whatever is installed.
REGISTRY_SNAPSHOT = frozenset("""
ACTUAL_API_KEY AI_GATEWAY_API_KEY ALIBABA_CODING_PLAN_API_KEY ALIBABA_CODING_PLAN_CN_API_KEY
ALIBABA_TOKEN_PLAN_API_KEY ALIBABA_TOKEN_PLAN_CN_API_KEY ANTHROPIC_API_KEY ANTHROPIC_TOKEN ARCEEAI_API_KEY
AZURE_FOUNDRY_API_KEY CLAUDE_CODE_OAUTH_TOKEN COMMANDCODE_API_KEY DASHSCOPE_API_KEY DEEPINFRA_API_KEY
DEEPSEEK_API_KEY FIREWORKS_API_KEY GEMINI_API_KEY GLM_API_KEY GMI_API_KEY GOOGLE_API_KEY HF_TOKEN
KILOCODE_API_KEY KIMI_API_KEY KIMI_CN_API_KEY KIMI_CODING_API_KEY LM_API_KEY META_API_KEY META_MODEL_API_KEY
MINIMAX_API_KEY MINIMAX_CN_API_KEY MODEL_API_KEY NEBIUS_API_KEY NEBIUS_TOKEN_FACTORY_API_KEY NOVITA_API_KEY
NVIDIA_API_KEY OLLAMA_API_KEY OPENAI_API_KEY OPENCODE_GO_API_KEY OPENCODE_ZEN_API_KEY RAMP_ROUTER_API_KEY
ROUTER_API_KEY STEPFUN_API_KEY TOKENHUB_API_KEY TOKENPLAN_API_KEY UPSTAGE_API_KEY XAI_API_KEY XIAOMI_API_KEY
ZAI_API_KEY Z_AI_API_KEY OPENROUTER_API_KEY MISTRAL_API_KEY GROQ_API_KEY TOGETHER_API_KEY PERPLEXITY_API_KEY
COHERE_API_KEY""".split())
UPSTREAM_ENV_KEYWORDS = ("env_vars", "api_key_env_vars", "base_url_env_var")
_ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{1,127}", re.ASCII)


def _ast_env_names(path):
    """Env var names a hermes-agent source file declares for providers: string constants under an
    env_vars= / api_key_env_vars= / base_url_env_var= keyword, and auth.py _REGISTRY_ROWS tuple rows
    (id, name, url, (KEYS...), BASE_URL_VAR, ...). Parsed, never imported or executed."""
    import ast
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        return set()
    out = set()
    def strs(node):
        return {c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)
                and _ENV_NAME_RE.fullmatch(c.value)}
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in UPSTREAM_ENV_KEYWORDS:
            out |= strs(node.value)
        targets = (node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(getattr(t, "id", None) == "_REGISTRY_ROWS" for t in targets) and isinstance(node.value, ast.Tuple):
            for row in node.value.elts:
                if isinstance(row, ast.Tuple):
                    for el in row.elts[3:5]:
                        out |= strs(el)
    return out


_UPSTREAM_ENV_CACHE = {}


def upstream_provider_env_names(roots=None):
    """Provider credential / base-url env names of the installed hermes-agent (Boundary B3), read from
    its source: hermes_cli/auth.py and plugins/model-providers/*/__init__.py under the first root
    that has hermes_cli (HERMES_SP, FAMILIA_HERMES_SRC, snap, FreeBSD ports). Empty when no tree is
    found; the static CLOUD_KEY_NAMES / regex / AWS_* superset still applies. Warns (Boundary B3a)
    when a parsed set is far smaller than REGISTRY_SNAPSHOT (likely a half-parsed auth.py)."""
    if roots is None:
        roots = (HERMES_SP, os.environ.get("FAMILIA_HERMES_SRC"), SNAP_SP, FREEBSD_LIB)
    for root in filter(None, roots):
        auth = os.path.join(root, "hermes_cli", "auth.py")
        if not os.path.isfile(auth):
            continue
        if root not in _UPSTREAM_ENV_CACHE:
            names = _ast_env_names(auth)
            for f in sorted(glob.glob(os.path.join(root, "plugins", "model-providers", "*", "__init__.py"))):
                names |= _ast_env_names(f)
            parsed = frozenset(n for n in names if not n.startswith("FAMILIA_"))
            # Boundary B3a: a real install should be near the snapshot size; half-or-less means the
            # AST walk likely missed _REGISTRY_ROWS / plugin env_vars.
            if parsed and len(parsed) * 2 < len(REGISTRY_SNAPSHOT):
                print(f"hermes.sh: warning: parsed upstream provider env set ({len(parsed)}) is far "
                      f"smaller than the v0.22.6 snapshot ({len(REGISTRY_SNAPSHOT)}); check {auth}",
                      file=sys.stderr)
            _UPSTREAM_ENV_CACHE[root] = parsed
        return _UPSTREAM_ENV_CACHE[root]
    return frozenset()


def is_llm_provider_key(name, upstream=None):
    """A cloud LLM provider credential / endpoint name: upstream's registry (installed source or the
    v0.22.6 snapshot), the static CLOUD_KEY_NAMES, or AWS_*. Not every *_API_KEY (BRAVE_SEARCH_API_KEY
    is a tool key an MCP server may legitimately need)."""
    if name.startswith("FAMILIA_"):
        return False
    upstream = upstream_provider_env_names() if upstream is None else upstream
    return (name in CLOUD_KEY_NAMES or name in REGISTRY_SNAPSHOT or name in upstream
            or name.startswith(CLOUD_KEY_PREFIXES))


def is_cloud_key(name, upstream=None):
    """What the child-env scrub drops: LLM provider names plus any *_API_KEY / *_API_TOKEN."""
    if name.startswith("FAMILIA_"):
        return False
    return is_llm_provider_key(name, upstream) or bool(CLOUD_KEY_RE.match(name))


def _no_creds_dir(env, name):
    """Private empty dir HERMES_HOME/.no-cloud-creds/<name> (0700) when HERMES_HOME is an existing
    directory (every launch), else os.devnull (probes such as --version / --help)."""
    home = env.get("HERMES_HOME")
    if not home or not os.path.isdir(home) or os.path.islink(home):
        return os.devnull
    try:
        ensure_private_dir(os.path.join(home, ".no-cloud-creds"))
        return ensure_private_dir(os.path.join(home, ".no-cloud-creds", name))
    except (OSError, SystemExit):
        return os.devnull


# Ambient non-LLM secrets (Boundary N2 / N2a): the hermes terminal tool inherits the child env, so
# model output running `env` would see them. Dropped unless FAMILIA_HERMES_PASS_SECRETS=1; graph-
# declared MCP names and harness control vars (HARNESS_ENV_KEEP) are kept. Secret-shaped names are
# matched first (so FAMILIA_GH_TOKEN / HERMES_TOKEN drop); the keep set is applied after.
PASS_SECRETS_ENV = "FAMILIA_HERMES_PASS_SECRETS"
AMBIENT_SECRET_NAMES = frozenset({
    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
    "SSH_AUTH_SOCK", "DSN", "DATABASE_URL", "KUBECONFIG", "REDIS_URL",
    "AMQP_URL", "RABBITMQ_URL", "CLOUDAMQP_URL", "MONGODB_URI", "PGPASSWORD", "MYSQL_PWD",
})
# Name shapes (applied before any FAMILIA_*/HERMES_* keep): *_SECRET/_PASSWORD/_PWD/_TOKEN/…
# plus DB/cache connection URL names and *AMQP*_URL. *_URI is value-based (see below), not a
# blanket name drop (REDIRECT_URI and similar stay unless the value is a credential DSN).
AMBIENT_SECRET_RE = re.compile(
    r"^(?:"
    r"[A-Za-z0-9_]*_(?:SECRET|SECRET_KEY|PASSWORD|PASSWD|PWD|TOKEN|PRIVATE_KEY|DSN|DATABASE_URL|DB_URL|REDIS_URL)"
    r"|(?:MONGO|POSTGRES|MYSQL|MARIADB|RABBITMQ)[A-Za-z0-9_]*_(?:URL|URI)"
    r"|[A-Za-z0-9_]*AMQP[A-Za-z0-9_]*_(?:URL|URI)"
    r")$"
)
# Userinfo forms (applied to the raw value and after percent-decode, so %40 counts as @):
#   scheme://userinfo@host  (any userinfo, including token@host)
#   //userinfo@host         (scheme-relative)
#   user:pass@host          (schemeless, password present)
#   user@host:port or user@host/path or user@host:path  (scp/ssh-style)
# A whole-value plain email (alice@example.com) is kept, so harmless vars like ADMIN_EMAIL
# are not scrubbed. Prefer dropping when the shape is ambiguous.
CREDENTIAL_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/\s@]+@")
CREDENTIAL_SCHEME_RELATIVE_RE = re.compile(r"^//[^/\s@]+@")
CREDENTIAL_SCHEMELESS_PASS_RE = re.compile(r"^[^/\s:@]+:[^/\s@]*@")
# user@host:port, user@host:path (git@host:org/repo), or user@host/path
CREDENTIAL_SCHEMELESS_SCP_RE = re.compile(r"^[^/\s:@]+@[^/\s:@]+(?::[^\s]+|/)")
# Bare user@host (no scheme, no password, no path). user@localhost drops; emails are
# skipped earlier by PLAIN_EMAIL_RE.
CREDENTIAL_SCHEMELESS_USERHOST_RE = re.compile(r"^[^/\s:@]+@[^/\s:@]+$")
PLAIN_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# Schemes whose `scheme:user@host` form is not a credential DSN (mailto:alice@example.com
# would otherwise look like schemeless user:pass@host).
HARMLESS_URI_SCHEMES = frozenset({"mailto", "tel", "sms", "urn", "tag", "cid", "mid"})
# Schemes that are credential DSNs even without userinfo; used only for *_URI value-based drops.
CREDENTIAL_DSN_SCHEMES = frozenset({
    "postgres", "postgresql", "mysql", "mariadb", "mongodb", "mongodb+srv",
    "redis", "rediss", "amqp", "amqps",
})
# Harness / launch control vars that must survive scrub even if a future pattern widened.
HARNESS_ENV_KEEP = frozenset({
    "HERMES_HOME", "HERMES_BIN", "HERMES_PY", "HERMES_SP", "HERMES_EXEC",
    "FAMILIA_HERMES_PASS_SECRETS", "FAMILIA_HERMES_ALLOW_CLOUD", "FAMILIA_HERMES_TOOLCHAIN_CHECK",
    "FAMILIA_HERMES_PIN_CHECK", "FAMILIA_HERMES_SRC", "FAMILIA_HERMES_CLIENT_PROBE",
    "FAMILIA_HERMES_ENV_PROBE_REFRESH", "FAMILIA_HERMES_DOGFOOD_YOLO", "FAMILIA_HERMES_UPSTREAM_PY",
    "FAMILIA_HERMES_TEST_PY", "FAMILIA_SYNC", "FAMILIA_API_KEY", "FAMILIA_PREFIX_CHILD",
    "FAMILIA_WARM_MIN_AVAIL_MIB", "FAMILIA_WARM_TIMEOUT", "FAMILIA_CHANNEL", "FAMILIA_STABLE_DAYS",
    "FAMILIA_HOST",
})


def _ambient_secret_name(name):
    """True when *name* is an ambient secret shape (no FAMILIA_/HERMES_ exemption)."""
    return name in AMBIENT_SECRET_NAMES or bool(AMBIENT_SECRET_RE.match(name))


def _percent_decode_value(val, rounds=3):
    """Decode %XX sequences a few times so %40 and %2540 surface as @."""
    s = val
    for _ in range(rounds):
        nxt = urllib.parse.unquote(s)
        if nxt == s:
            break
        s = nxt
    return s


def _credential_url_candidates(val):
    raw = val.strip()
    out = [raw]
    dec = _percent_decode_value(raw)
    if dec != raw:
        out.append(dec.strip())
    return out


def _credential_url_value(val):
    """True when *val* has URL userinfo: scheme://userinfo@, //userinfo@, schemeless
    user:pass@host, or scp/ssh user@host:path / user@host/path, including after %40
    decode. A whole-value plain email (alice@example.com) is kept."""
    if not isinstance(val, str):
        return False
    for s in _credential_url_candidates(val):
        if not s:
            continue
        if PLAIN_EMAIL_RE.match(s):
            continue
        # mailto:alice@example.com (and similar) is not user:pass@host.
        if "://" not in s and ":" in s:
            head = s.split(":", 1)[0].lower()
            if head in HARMLESS_URI_SCHEMES:
                continue
        if (CREDENTIAL_URL_RE.match(s) or CREDENTIAL_SCHEME_RELATIVE_RE.match(s)
                or CREDENTIAL_SCHEMELESS_PASS_RE.match(s)
                or CREDENTIAL_SCHEMELESS_SCP_RE.match(s)
                or CREDENTIAL_SCHEMELESS_USERHOST_RE.match(s)):
            return True
    return False


def _credential_dsn_uri(name, val):
    """True for a *_URI whose value is a known credential DSN scheme (postgres://, mongodb://, …)."""
    if not isinstance(name, str) or not name.endswith("_URI") or not isinstance(val, str):
        return False
    if "://" not in val:
        return False
    return val.strip().split("://", 1)[0].lower() in CREDENTIAL_DSN_SCHEMES


def scrub_ambient_secrets(env, keep=()):
    """Drop ambient non-LLM secrets from *env* (in place) unless FAMILIA_HERMES_PASS_SECRETS=1.

    Name shapes (matched before keep): GH_TOKEN/…/KUBECONFIG/AMQP_URL/RABBITMQ_URL/CLOUDAMQP_URL/
    *AMQP*_URL/MONGODB_URI/PGPASSWORD/MYSQL_PWD, *_SECRET/*_PASSWORD/*_PWD/*_TOKEN/*_PRIVATE_KEY/
    *_DSN/*_DATABASE_URL/*_DB_URL/*_REDIS_URL, MONGO*/POSTGRES*/MYSQL*/RABBITMQ*_URL/_URI. Also
    any var whose value has URL userinfo (scheme://userinfo@, //userinfo@, schemeless
    user:pass@host, or scp/ssh user@host:path, including after %40-decode). A whole-value
    plain email is kept. *_URI is value-based: dropped only when the value has userinfo or a
    known credential DSN scheme (REDIRECT_URI stays).
    Keep = caller keep | MCP_ENV_KEEP | HARNESS_ENV_KEEP. Returns the names removed."""
    if env.get(PASS_SECRETS_ENV) == "1":
        return []
    keep = set(keep) | MCP_ENV_KEEP | HARNESS_ENV_KEEP
    gone = sorted(
        k for k, v in env.items()
        if k not in keep and (_ambient_secret_name(k) or _credential_url_value(v)
                              or _credential_dsn_uri(k, v))
    )
    for k in gone:
        del env[k]
    return gone


def isolate_file_creds(env):
    """Point the file-based cloud credential chains hermes would read regardless of HERMES_HOME
    away from the user's files (unless FAMILIA_HERMES_ALLOW_CLOUD=1): boto (~/.aws -> /dev/null,
    no EC2/ECS metadata), Codex (CODEX_HOME), gcloud ADC (CLOUDSDK_CONFIG). Files found only via
    $HOME (~/.qwen/oauth_creds.json, ~/.claude) cannot be redirected without moving HOME."""
    if allow_cloud(env):
        return env
    env.update(AWS_SHARED_CREDENTIALS_FILE=os.devnull, AWS_CONFIG_FILE=os.devnull,
               AWS_EC2_METADATA_DISABLED="true", CODEX_HOME=_no_creds_dir(env, "codex"),
               CLOUDSDK_CONFIG=_no_creds_dir(env, "gcloud"))
    return env


MCP_ENV_KEEP = set()   # names declared by the rendered agent's MCP servers (render() fills it)


def allow_cloud(environ=None):
    return (os.environ if environ is None else environ).get(ALLOW_CLOUD_ENV) == "1"


def scrub_cloud_keys(env, keep=()):
    """Drop cloud LLM credentials from *env* (in place) unless FAMILIA_HERMES_ALLOW_CLOUD=1.
    Returns the sorted names removed (never their values)."""
    if allow_cloud(env):
        return []
    keep = set(keep) | MCP_ENV_KEEP
    upstream = upstream_provider_env_names()
    gone = sorted(k for k in env if k not in keep and is_cloud_key(k, upstream))
    for k in gone:
        del env[k]
    return gone


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


CONFIG_HEADER = "# Generated by familia scripts/hermes_harness.py from graph.yaml. Do not edit.\n"


def write_private(path, text):
    """Atomically replace *path* with *text*, mode 0600 from creation: the temp file is opened
    O_CREAT|O_EXCL|O_NOFOLLOW in the same directory (a planted file or symlink there is refused, not
    written through), fsynced, then os.replace()d over *path* (a symlink at *path* is replaced, never
    followed). Used for config.yaml (holds the familia API key) and SOUL.md."""
    import secrets
    d = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(d, f".{os.path.basename(path)}.familia-{os.getpid()}-{secrets.token_hex(6)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)   # umask can only narrow, but be explicit
        os.replace(tmp, path)
        try:   # durability of the rename (Boundary N4); best effort where dirs cannot be opened
            dfd = os.open(d, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    finally:
        if fd is not None:
            os.close(fd)
        if os.path.lexists(tmp):
            os.unlink(tmp)
    return path


def ensure_private_dir(path):
    """mkdir -p *path* 0700, then make sure it (new or pre-existing) is a real directory owned by
    this user and tighten it to 0700. A symlink, a non-directory or another owner is refused
    (SystemExit): sessions, state.db, logs and config.yaml (familia key) live below it. The checks
    and the chmod go through one O_NOFOLLOW|O_DIRECTORY fd (fstat + fchmod), so a swap between
    check and chmod cannot redirect the chmod."""
    import stat
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    except FileExistsError:
        pass   # a non-directory there: refused below
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        die(f"refusing {path}: it is a symlink (expected a private directory)")
    if not stat.S_ISDIR(st.st_mode):
        die(f"refusing {path}: not a directory")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        if st.st_uid != os.geteuid():
            die(f"refusing {path}: owned by uid {st.st_uid}, not {os.geteuid()}")
        if stat.S_IMODE(st.st_mode) != 0o700:
            os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
    return path


def write_config(path, cfg):
    write_private(path, CONFIG_HEADER + yaml.safe_dump(cfg, sort_keys=False))


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
    write_config(path, cfg)
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
    Cloud LLM keys are removed unless FAMILIA_HERMES_ALLOW_CLOUD=1 (scrub_cloud_keys); ambient
    secrets (name shapes + scheme://userinfo@ values, incl. token@host; FAMILIA_GH_TOKEN/HERMES_TOKEN included)
    unless FAMILIA_HERMES_PASS_SECRETS=1 (scrub_ambient_secrets).
    """
    env = dict(os.environ if environ is None else environ)
    scrub_cloud_keys(env)   # before extra: values the harness passes on purpose are kept
    scrub_ambient_secrets(env)
    if extra:
        env.update(extra)
    isolate_file_creds(env)
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
# TODO(pentest-policy): tools-confirm must not open until every tool call (MCP and
# all toolsets) goes through per-action confirmation; setting approvals.mode=manual
# alone is not enough. Also needs graph_types accepting `pentests.<p>.policy` (today
# tests/test_config_spec.py strict-xfails until then). When both land, open tools for
# mode `tools-confirm` (and `autonomous-lab`) via pentest_tools_allowed() below:
#   - route_tools → mode=direct on the pentest node
#   - render sets approvals.mode=manual (no yolo / mode=off) — necessary but not
#     sufficient; every MCP and toolset call must still confirm per action
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
    """Same-host / mesh fallback candidate: active, not self, not fail-closed, capable, and
    vg.tool_policy != [] (#243 / Boundary B1). tool_policy already yields [] for
    server_tools opt-out (none/[]/false) and for a capable non-loopback peer with no
    server_tools key — so requiring != [] skips both without a second bind check."""
    o = (g.get("nodes") or {}).get(k) or {}
    return (k != src and o.get("status") != "planned"
            and not tool_free(g, k) and vg.tool_capable(g, k)
            and vg.tool_policy(g, k) != [])


def route_tools(g, agent):
    """-> {"mode": none|direct|nexus, "node", "via"}.
    Reuses validate_graph.tool_capable / tool_route / tool_policy (#243). Explicit
    nodes.<n>.tool_route wins as the nexus target; same-host then mesh discovery is the
    Hermes-only fallback when #243 has no route. Never into guardian/pentest/defender."""
    _, name, n, _ = node_for(g, agent)
    if tool_free(g, name):
        return {"mode": "none", "node": None, "via": None, "reason": "tool-free node"}
    if vg.tool_capable(g, name):
        # Explicit server_tools opt-out (TOOLS-006): present key whose policy is [] → none.
        # Missing key stays direct even if policy would be [] for other reasons (e.g. off-loopback).
        if "server_tools" in n and vg.tool_policy(g, name) == []:
            return {"mode": "none", "node": None, "via": None, "reason": "server_tools opt-out"}
        return {"mode": "direct", "node": name, "via": None}
    # Explicit one-hop from graph (#243). Reject fail-closed and policy-[] targets here too
    # (vg.tool_route already filters policy-[], but keep the check so a [] grant is never used).
    t = vg.tool_route(g, name)
    if t and not tool_free(g, t) and vg.tool_policy(g, t) != []:
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
    # approvals.mode=manual here (never off / yolo). That alone is not enough —
    # tools-confirm must not open until every tool call (MCP and all toolsets) goes
    # through per-action confirmation (docs/config/pentest-policy.md CFG-PENT-MODE-004).
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
    local_only = not allow_cloud()
    if local_only:
        for t in MODAL_AUX_TASKS:
            aux[t] = {"provider": "custom", "model": alias, "base_url": base,
                      "api_key": familia_auth.api_key() or "local", "timeout": comp.get("aux_timeout", 3600)}
        # Explicit presets map is authoritative upstream (moa_config.apply_user_moa_presets), so this
        # replaces the built-in cloud preset rather than merging with it; disabled as well.
        cfg["moa"] = {"default_preset": "default", "active_preset": "",
                      "presets": {"default": {"enabled": False,
                                              "reference_models": [{"provider": "custom", "model": alias, "enabled": True}],
                                              "aggregator": {"provider": "custom", "model": alias}}}}
    cfg["auxiliary"] = aux
    MCP_ENV_KEEP.clear()
    declared_env = mcp_env_allowlist(a)
    # Boundary N3: a graph-declared MCP name that is a cloud LLM provider credential (OPENAI_API_KEY,
    # AWS_*, a registry name; not tool keys like BRAVE_SEARCH_API_KEY) would re-admit it into hermes' whole env, not only that server's. Local-only
    # mode does not keep it: the server's ${VAR} stays unset (upstream drops unset refs). hermes
    # interpolates MCP env from its own process env, so scoping the value to one server would need
    # it on disk; FAMILIA_HERMES_ALLOW_CLOUD=1 keeps it (whole env) as before.
    refused = [] if not local_only else [n for n in declared_env if is_llm_provider_key(n)]
    if refused:
        print(f"hermes.sh: warning: not passing cloud credential(s) {', '.join(refused)} declared by "
              f"agents.{agent}.mcp (FAMILIA_HERMES_ALLOW_CLOUD=1 passes them)", file=sys.stderr)
    MCP_ENV_KEEP.update(n for n in declared_env if n not in refused)
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
    ensure_private_dir(os.path.dirname(home))   # ~/.cache/familia (B1: existing dirs too)
    ensure_private_dir(home)                    # ~/.cache/familia/hermes-<agent>
    write_config(os.path.join(home, "config.yaml"), cfg)   # 0600: it holds the familia API key
    link_plugins(a, home)
    link_reaches(g, agent, home)
    greet_soul(home)
    return home, base, n, name


def _default_soul_text():
    """hermes-agent's own DEFAULT_SOUL_MD (what it seeds into an empty HERMES_HOME), read as a literal
    from hermes_cli/default_soul.py without importing hermes. None when no hermes tree is found."""
    import ast
    for sp in (HERMES_SP, os.environ.get("FAMILIA_HERMES_SRC"), SNAP_SP, FREEBSD_LIB):
        f = os.path.join(sp, "hermes_cli", "default_soul.py") if sp else None
        if not (f and os.path.isfile(f)):
            continue
        try:
            for node in ast.parse(open(f, encoding="utf-8").read()).body:
                if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DEFAULT_SOUL_MD" for t in node.targets):
                    v = ast.literal_eval(node.value)
                    return v if isinstance(v, str) else None
        except (OSError, SyntaxError, ValueError):
            continue
    return None


def _read_nofollow(p):
    """Text of regular file *p* opened O_NOFOLLOW|O_NONBLOCK (a symlink swapped in after the islink
    check fails with ELOOP instead of being followed; a FIFO cannot block), or None when absent."""
    import errno, stat
    try:
        fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                     | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise OSError(errno.ELOOP, f"{p} is a symlink (not followed)")
        raise
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise OSError(errno.EINVAL, f"{p} is not a regular file")
        return f.read().decode("utf-8-sig")


def greet_soul(home):
    """Fleet greeting (docs/FLEET-GREETING.md, scripts/fleet_greeting.py) at the start of the rendered
    HERMES_HOME/SOUL.md, hermes' identity slot #1, so it opens the system prompt. Exactly once; the
    rest of SOUL.md (harness2-managed text, or hermes' default identity when there is none) follows
    unchanged. Every agent, pentest and guardian included (text only, no tools). Best effort: a missing
    greeting or an unwritable SOUL.md is a warning, never a failed launch. Returns the SOUL.md path or None."""
    p = os.path.join(home, "SOUL.md")
    try:
        import fleet_greeting as FG
        if os.path.islink(p):
            print(f"hermes.sh: fleet greeting skipped: {p} is a symlink (not written through)", file=sys.stderr)
            return None
        cur = _read_nofollow(p)
        body = cur if cur is not None else (_default_soul_text() or "")
        new = FG.prepend(body)
        if new == (cur if cur is not None else "") or (cur is None and not new):
            return p if cur is not None else None
        write_private(p, new)   # O_CREAT|O_EXCL|O_NOFOLLOW temp, 0600, fsync, atomic replace
        return p
    except Exception as e:  # never fail a launch over the greeting
        print(f"hermes.sh: fleet greeting skipped ({e.__class__.__name__}: {e})", file=sys.stderr)
        return None


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
    launch_env = hermes_child_env({"HERMES_HOME": home})
    executable, full = hermes_exec_argv(HERMES_BIN, HERMES_EXEC, argv, launch_env)
    return subprocess.call(full, executable=executable,
                           env=launch_env,
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


def hermes_exec_argv(bin_path, exec_path, argv, env):
    """Return ``(executable, full_argv)`` for launching hermes (Boundary N1 / N1a).

    Default: trusted realpath (*exec_path*) with argv0=*bin_path*. When the binary has an
    ``#!/usr/bin/env CMD`` shebang, resolve CMD against the child PATH in *env* (which prepends
    ``HERMES_HOME/bin``), trust that interpreter, and return it as the executable with the script
    as argv[1] so the kernel cannot pick a different CMD than the one we checked.
    """
    target = exec_path or bin_path
    if target and _is_env_shebang(target):
        interp = _read_shebang(target, path_env=(env or {}).get("PATH"))
        if not interp or not os.path.isabs(str(interp)):
            die(f"env shebang interpreter for {target!r} not found on child PATH")
        real_i, why = trust_exec(interp, interpreter=False)
        if why:
            die(f"child PATH interpreter {interp!r}: {why}")
        return real_i, [real_i, target] + list(argv)
    return target, [bin_path] + list(argv)


def exec_hermes(bin_path, exec_path, argv, env):
    """``os.execv`` hermes using :func:`hermes_exec_argv` (does not return)."""
    executable, full = hermes_exec_argv(bin_path, exec_path, argv, env)
    os.execv(executable, full)


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
    exec_hermes(HERMES_BIN, HERMES_EXEC, argv, launch_env)   # trusted realpath; N1a env-shebang


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
