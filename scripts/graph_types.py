"""Typed schema for the familia declarative graph (graph.yaml, version 2).

Every section of graph.yaml is a *type* registered in TYPES.  A type is a
field spec (required fields, no defaults) plus an optional cross-check
function.  Adding a refined or new type = one TYPES entry + one checker.
See docs/graph-types.md.
"""
import ipaddress
import re

# ---- field specs -----------------------------------------------------------
class F:
    """Field spec. kind: str|int|bool|enum|ref|refs|map|list|sha."""
    def __init__(self, kind, *, ref=None, choices=None, min=None, optional=False, nullable=False):
        self.kind, self.ref, self.choices, self.min = kind, ref, choices, min
        self.optional, self.nullable = optional, nullable

def req(kind, **kw): return F(kind, **kw)
def opt(kind, **kw): return F(kind, optional=True, **kw)

SHA_RE = re.compile(r"^[0-9a-f]{64}$")

def check_field(g, sec, name, key, spec, val, errs):
    where = f"{sec}.{name}.{key}"
    if val is None:
        if not spec.nullable: errs.append(f"{where}: must not be null")
        return
    k = spec.kind
    if k == "int":
        if not isinstance(val, int) or isinstance(val, bool): errs.append(f"{where}: expected integer, got {val!r}")
        elif spec.min is not None and val < spec.min: errs.append(f"{where}: {val} < minimum {spec.min}")
    elif k == "str":
        if not isinstance(val, str) or not val: errs.append(f"{where}: expected non-empty string, got {val!r}")
    elif k == "bool":
        if not isinstance(val, bool): errs.append(f"{where}: expected true/false, got {val!r}")
    elif k == "enum":
        if val not in spec.choices: errs.append(f"{where}: {val!r} not one of {sorted(spec.choices)}")
    elif k == "sha":
        if val != "unmeasured" and not (isinstance(val, str) and SHA_RE.match(val)):
            errs.append(f"{where}: expected 64 lowercase hex chars or the literal 'unmeasured', got {val!r}")
    elif k == "list":
        if not isinstance(val, list) or not val or not all(isinstance(x, str) and x for x in val):
            errs.append(f"{where}: expected non-empty list of strings")
    elif k == "ref":
        if not isinstance(val, str): errs.append(f"{where}: expected a {spec.ref} name, got {val!r}")
        elif val not in (g.get(spec.ref) or {}): errs.append(f"{where}: no such {spec.ref} entry {val!r}")
    elif k == "refs":
        if not isinstance(val, list) or not val or not all(isinstance(v, str) for v in val):
            errs.append(f"{where}: expected non-empty list of {spec.ref} names"); return
        if len(set(map(str, val))) != len(val): errs.append(f"{where}: duplicate entries")
        for v in val:
            if v not in (g.get(spec.ref) or {}): errs.append(f"{where}: no such {spec.ref} entry {v!r}")
    elif k == "any":
        pass
    elif k == "num":
        if not isinstance(val, (int, float)) or isinstance(val, bool): errs.append(f"{where}: expected number, got {val!r}")
    elif k == "strlist":
        if not isinstance(val, list) or not all(isinstance(x, str) and x for x in val): errs.append(f"{where}: expected list of strings (may be empty)")
    elif k == "gpus":
        if not isinstance(val, list): errs.append(f"{where}: expected list of GPUs ([] if none known)")
    elif k == "map":
        if not isinstance(val, dict) or not val: errs.append(f"{where}: expected non-empty mapping")
    else:
        raise AssertionError(k)

# ---- cross-checks ----------------------------------------------------------
def lookup(g, sec, key):
    """Entry `key` of section `sec`, or None (also for malformed, unhashable keys)."""
    return (g.get(sec) or {}).get(key) if isinstance(key, str) else None

HOST_FACTS = ("os", "cpu", "threads", "ram_mib", "gpus", "reserve_ram_mib")
GPU_BACKENDS = {"cuda", "cuda-sm11-ptx", "vulkan", "sycl", "metal", "opencl", "rocm", "none"}
GPU_KEYS = {"vendor", "model", "vram_mib", "backend", "backend_status", "compute_capability", "driver", "measured", "notes"}
GPU_REQUIRED = ("vendor", "model", "vram_mib", "backend", "backend_status", "measured")
WINDOWS_KEYS = ("repo_path", "models_path", "runtime_path", "startup", "wake")
WINDOWS_STARTUP = {"scheduled-task", "start.bat", "service", "manual", "tbd"}
WINDOWS_OPT_KEYS = ("start_script", "task_name", "autostart", "avx_required")  # #17

def check_host(g, name, h, errs):
    if h.get("measured") is True:
        for k in HOST_FACTS:
            if k not in h: errs.append(f"hosts.{name}: measured host missing required '{k}'")
        if h.get("kind") == "unknown": errs.append(f"hosts.{name}: measured host cannot have kind 'unknown'")
        if "reported" in h: errs.append(f"hosts.{name}: 'reported' is only for unmeasured hosts")
        if isinstance(h.get("ram_mib"), int) and isinstance(h.get("reserve_ram_mib"), int) and h["reserve_ram_mib"] >= h["ram_mib"]:
            errs.append(f"hosts.{name}: reserve_ram_mib >= ram_mib leaves nothing for nodes")
    elif h.get("measured") is False:
        for k in ("threads", "ram_mib", "vram_mib", "reserve_ram_mib"):
            if k in h: errs.append(f"hosts.{name}: '{k}' given but measured is false; record only measured facts (set measured: true)")
        rep = h.get("reported")
        if rep is not None and not (isinstance(rep, dict) and isinstance(rep.get("source"), str)):
            errs.append(f"hosts.{name}.reported: must be a mapping with a 'source' (where the unmeasured facts came from)")
    check_gpus(name, h, errs)
    win = h.get("windows")
    if h.get("os") == "windows" and not isinstance(win, dict):
        errs.append(f"hosts.{name}: os windows requires a 'windows' block ({', '.join(WINDOWS_KEYS)}; TBD allowed)")
    if win is not None:
        if h.get("os") != "windows": errs.append(f"hosts.{name}: 'windows' block requires os: windows")
        elif isinstance(win, dict):
            for k in WINDOWS_KEYS:
                if k not in win: errs.append(f"hosts.{name}.windows: missing required '{k}' (use TBD/tbd if unknown)")
            for k in win:
                if k not in WINDOWS_KEYS + WINDOWS_OPT_KEYS: errs.append(f"hosts.{name}.windows: unknown field {k!r}")
            if "startup" in win and win["startup"] not in WINDOWS_STARTUP:
                errs.append(f"hosts.{name}.windows.startup: {win['startup']!r} not one of {sorted(WINDOWS_STARTUP)}")
            for k in ("autostart", "avx_required"):
                if k in win and not isinstance(win[k], bool): errs.append(f"hosts.{name}.windows.{k}: expected true/false")
            st = win.get("startup")
            if st in ("start.bat", "scheduled-task") and not win.get("start_script"):
                errs.append(f"hosts.{name}.windows: startup {st} needs start_script")
            if st == "scheduled-task" and not win.get("task_name"):
                errs.append(f"hosts.{name}.windows: startup scheduled-task needs task_name")
            if win.get("autostart") is True and st != "scheduled-task":
                errs.append(f"hosts.{name}.windows: autostart true needs startup scheduled-task (opt-in via install-task.ps1 -Install)")

def check_gpus(name, h, errs):
    gpus = h.get("gpus")
    if not isinstance(gpus, list): return
    for i, gp in enumerate(gpus):
        w = f"hosts.{name}.gpus[{i}]"
        if not isinstance(gp, dict): errs.append(f"{w}: expected mapping"); continue
        for k in GPU_REQUIRED:
            if k not in gp: errs.append(f"{w}: missing required '{k}' (null allowed where unknown)")
        for k in gp:
            if k not in GPU_KEYS: errs.append(f"{w}: unknown field {k!r}")
        if gp.get("backend") not in GPU_BACKENDS: errs.append(f"{w}.backend: {gp.get('backend')!r} not one of {sorted(GPU_BACKENDS)}")
        if gp.get("backend_status") not in ("verified", "tbd", "unsupported"):
            errs.append(f"{w}.backend_status: {gp.get('backend_status')!r} not one of ['tbd', 'unsupported', 'verified']")
        if not isinstance(gp.get("measured"), bool): errs.append(f"{w}.measured: expected true/false")
        v = gp.get("vram_mib")
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
            errs.append(f"{w}.vram_mib: expected integer >= 0 or null")
        if gp.get("measured") is not True:
            if v is not None: errs.append(f"{w}: vram_mib {v} given but measured is false; leave null until measured")
            if gp.get("backend_status") == "verified": errs.append(f"{w}: backend_status verified requires measured: true")
        elif v is None:
            errs.append(f"{w}: measured GPU needs vram_mib (0 for shared-memory iGPUs)")

def check_transport(g, name, t, errs):
    if t.get("kind") == "local" and t.get("from") != t.get("to"):
        errs.append(f"transports.{name}: kind local requires from == to")
    if t.get("kind") != "local" and t.get("from") == t.get("to"):
        errs.append(f"transports.{name}: kind {t.get('kind')} links a host to itself; use kind local")

def check_runtime(g, name, r, errs):
    if r.get("kind") == "llama-server":
        c = r.get("commit")
        # A git sha, or a distro package pin pkg:<name>=<version> (Termux llama-cpp reports no commit).
        if isinstance(c, str) and not re.match(r"^([0-9a-f]{7,40}|pkg:[a-z0-9][a-z0-9.+-]*=[0-9][A-Za-z0-9.+~-]*)$", c):
            errs.append(f"runtimes.{name}: commit {c!r} is not a git sha (a branch name is not a pin)")
    b = r.get("backends")
    if isinstance(b, list):
        bad = [x for x in b if x not in GPU_BACKENDS | {"cpu"}]
        if bad: errs.append(f"runtimes.{name}.backends: unknown {bad} (allowed: cpu + {sorted(GPU_BACKENDS - {'none'})})")
        if "cpu" not in b: errs.append(f"runtimes.{name}.backends: must include cpu")
    st = r.get("spec_types")
    if isinstance(st, list):
        bad = [x for x in st if x not in SPEC_TYPES]
        if bad: errs.append(f"runtimes.{name}.spec_types: unknown {bad}")

def slot_ctx(n):
    return n["ctx"] // n["parallel"] if isinstance(n.get("ctx"), int) and isinstance(n.get("parallel"), int) and n["parallel"] > 0 else None

def check_node(g, name, n, errs):
    h, r, m = lookup(g, "hosts", n.get("host")), lookup(g, "runtimes", n.get("runtime")), lookup(g, "models", n.get("model"))
    planned = n.get("status") == "planned"
    if h is not None and h.get("measured") is not True and not planned:
        errs.append(f"nodes.{name}: host {n['host']!r} is not measured; unmeasured hosts are excluded from placement")
    if r is not None and not planned and n.get("host") not in (r.get("hosts") or []):
        errs.append(f"nodes.{name}: runtime {n['runtime']!r} is not installed on host {n.get('host')!r} (runtime hosts: {r.get('hosts')})")
    if r is not None and m is not None and not planned and m.get("arch") not in (r.get("supported_archs") or []):
        errs.append(f"nodes.{name}: model {n['model']!r} arch {m.get('arch')!r} not in runtime {n['runtime']!r} "
                    f"(build {r.get('build')}) supported_archs {r.get('supported_archs')}; upgrade the runtime pin, do not drop the model")
    if isinstance(n.get("ctx"), int) and isinstance(n.get("parallel"), int) and n["parallel"] > 0 and n["ctx"] % n["parallel"]:
        errs.append(f"nodes.{name}: ctx {n['ctx']} not divisible by parallel {n['parallel']}")
    s = slot_ctx(n)
    if m is not None and s is not None and isinstance(m.get("trained_ctx"), int) and s > m["trained_ctx"]:
        errs.append(f"nodes.{name}: per-slot ctx {s} exceeds model trained_ctx {m['trained_ctx']} (no inflation)")
    check_offload(name, n, h, r, errs)
    for other, o in (g.get("nodes") or {}).items():
        if other < name and "planned" not in (o.get("status"), n.get("status")) and o.get("host") == n.get("host") and o.get("port") == n.get("port"):
            errs.append(f"nodes.{name}: port {n.get('port')} on host {n.get('host')!r} also used by node {other!r}")

SPLIT_MODES = {"none", "layer", "row", "tensor"}  # llama-server -sm (b11374/b11539 --help)

def check_offload(name, n, h, r, errs):
    o = n.get("offload")
    if not isinstance(o, dict): return
    w = f"nodes.{name}.offload"
    for k in ("backend", "ngl", "split", "main_gpu"):
        if k not in o: errs.append(f"{w}: missing required '{k}' (no defaults)")
    for k in o:
        if k not in ("backend", "ngl", "split", "main_gpu", "vram_reserve_mib"): errs.append(f"{w}: unknown field {k!r}")
    be, ngl, mg = o.get("backend"), o.get("ngl"), o.get("main_gpu")
    if be not in GPU_BACKENDS | {"cpu"} or be == "none": errs.append(f"{w}.backend: {be!r} must be cpu or one of {sorted(GPU_BACKENDS - {'none'})}")
    if o.get("split") not in SPLIT_MODES: errs.append(f"{w}.split: {o.get('split')!r} not one of {sorted(SPLIT_MODES)}")
    if not isinstance(ngl, int) or isinstance(ngl, bool) or ngl < 0: errs.append(f"{w}.ngl: expected integer >= 0"); return
    if not isinstance(mg, int) or isinstance(mg, bool) or mg < 0: errs.append(f"{w}.main_gpu: expected integer >= 0"); return
    if be == "cpu":
        if ngl: errs.append(f"{w}: backend cpu requires ngl 0")
        return
    if r is not None and be not in (r.get("backends") or []):
        errs.append(f"{w}: backend {be!r} not in runtime {n.get('runtime')!r} backends {r.get('backends')}")
    if ngl == 0 or n.get("status") == "planned": return
    gpus = (h or {}).get("gpus") or []
    if mg >= len(gpus): errs.append(f"{w}: main_gpu {mg} but host {n.get('host')!r} declares {len(gpus)} GPU(s)"); return
    gp = gpus[mg]
    if gp.get("backend") != be: errs.append(f"{w}: backend {be!r} but GPU {mg} backend is {gp.get('backend')!r}")
    if gp.get("measured") is not True or gp.get("backend_status") != "verified":
        errs.append(f"{w}: ngl {ngl} on unmeasured/unverified GPU {mg} ({gp.get('model')}); measure it and set backend_status verified first")
    elif gp.get("vram_mib") == 0 and gp.get("vendor") not in ("intel", "qualcomm", "arm", "apple"):
        errs.append(f"{w}: ngl {ngl} but GPU {mg} has vram_mib 0")

SPEC_TYPES = {"draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash", "draft-dspark",
              "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-mod", "ngram-cache"}

def check_speculative(g, name, sp, errs):
    w = f"speculative.{name}"
    t = lookup(g, "nodes", sp.get("target"))
    rt = lookup(g, "runtimes", t.get("runtime")) if t else None
    st = sp.get("spec_type")
    mode = sp.get("mode")
    if mode == "draft":
        for k in ("draft", "draft_max", "draft_min", "p_min"):
            if k not in sp: errs.append(f"{w}: mode draft requires '{k}'")
        if st is not None and not str(st).startswith("draft-"): errs.append(f"{w}: mode draft needs a draft-* spec_type, got {st!r}")
        d = lookup(g, "models", sp.get("draft"))
        tm = lookup(g, "models", t.get("model")) if t else None
        if d is not None and tm is not None and d is tm: errs.append(f"{w}: draft model is the target model")
        dm, dn = sp.get("draft_max"), sp.get("draft_min")
        if isinstance(dm, int) and isinstance(dn, int) and dn > dm: errs.append(f"{w}: draft_min {dn} > draft_max {dm}")
        p = sp.get("p_min")
        if p is not None and not (isinstance(p, (int, float)) and not isinstance(p, bool) and 0 <= p <= 1):
            errs.append(f"{w}.p_min: expected 0..1, got {p!r}")
    elif mode == "ngram":
        for k in ("draft", "draft_ctx", "draft_kv_type", "draft_ngl"):
            if k in sp: errs.append(f"{w}: '{k}' only applies to mode draft")
        if not (isinstance(st, str) and st.startswith("ngram-")): errs.append(f"{w}: mode ngram needs an ngram-* spec_type, got {st!r}")
    eff = st or ("draft-simple" if mode == "draft" else None)
    if rt is not None and eff and eff not in (rt.get("spec_types") or []):
        errs.append(f"{w}: runtime {t.get('runtime')!r} does not list spec_type {eff!r} (spec_types {rt.get('spec_types')}); TBD until verified")
    others = [o for o, x in (g.get("speculative") or {}).items() if x.get("target") == sp.get("target") and x.get("status") == "active" and o != name]
    if sp.get("status") == "active" and others: errs.append(f"{w}: target {sp.get('target')!r} already has active speculative {others}")

def check_alias(g, name, a, errs):
    gw, nd = lookup(g, "gateways", a.get("gateway")), lookup(g, "nodes", a.get("node"))
    if gw and nd and gw.get("host") != nd.get("host"):
        if not any(t.get("kind") != "local" and {t.get("from"), t.get("to")} == {gw.get("host"), nd.get("host")}
                   for t in (g.get("transports") or {}).values()):
            errs.append(f"aliases.{name}: gateway host {gw.get('host')!r} has no transport to node host {nd.get('host')!r}")

AGENT_ROLES = ("main", "auxiliary")

def check_agent(g, name, a, errs):
    al = a.get("aliases")
    if not isinstance(al, dict): return
    for role in al:
        if role not in AGENT_ROLES: errs.append(f"agents.{name}.aliases: unknown role {role!r} (roles: {list(AGENT_ROLES)})")
    for role in AGENT_ROLES:
        if role not in al: errs.append(f"agents.{name}.aliases: missing required role '{role}' (no defaults)")
    for role, target in al.items():
        if isinstance(target, list):
            errs.append(f"agents.{name}.aliases.{role}: exactly one alias per role, got a list"); continue
        alias = lookup(g, "aliases", target)
        if alias is None: errs.append(f"agents.{name}.aliases.{role}: no such alias {target!r}"); continue
        node = lookup(g, "nodes", alias.get("node"))
        s = slot_ctx(node) if node else None
        if s is None: continue
        if isinstance(a.get("min_ctx"), int) and s < a["min_ctx"]:
            errs.append(f"agents.{name}.aliases.{role}: alias {target!r} per-slot ctx {s} < agent min_ctx {a['min_ctx']}")
        if role == "main" and isinstance(a.get("context_length"), int) and a["context_length"] != s:
            errs.append(f"agents.{name}: context_length {a['context_length']} != alias {target!r} per-slot ctx {s} "
                        "(larger makes llama.cpp silently truncate; smaller wastes the window)")

def check_agency(g, name, a, errs):
    labels = a.get("labels") or []
    for label, agent in (a.get("assignments") or {}).items():
        if not isinstance(label, str) or label not in labels: errs.append(f"agencies.{name}.assignments: label {label!r} not in labels")
        if lookup(g, "agents", agent) is None: errs.append(f"agencies.{name}.assignments.{label}: no such agent {agent!r}")
    if isinstance(a.get("repo"), str) and not re.match(r"^[\w.-]+/[\w.-]+$", a["repo"]):
        errs.append(f"agencies.{name}.repo: expected owner/name, got {a['repo']!r}")

def check_council(g, name, c, errs):
    m = len(c.get("agents") or [])
    if c.get("mode") == "quorum":
        q = c.get("quorum")
        if not isinstance(q, int) or isinstance(q, bool): errs.append(f"councils.{name}: mode quorum requires integer 'quorum' (N of M)")
        elif not 1 <= q <= m: errs.append(f"councils.{name}: quorum {q} must be between 1 and {m} (number of agents)")
    elif c.get("mode") == "cascade" and "quorum" in c:
        errs.append(f"councils.{name}: 'quorum' only applies to mode quorum")


# Authorized testing of the owner's fleet only. Not attack tooling.
# Automated tests are launch-only: validate → start → healthcheck → stop.
# Never run live scans, exploits, network probes, or attack procedures in tests.
PENTEST_NETWORK_EXEC_TOOLS = frozenset({
    "network", "exec", "shell", "ssh", "nmap", "curl", "http", "https",
    "scan", "probe", "subprocess", "run_command", "tcp_connect", "udp_send",
    "nc", "netcat", "wget", "fetch",
})

def _scope_target_ok(s, hosts):
    """Host name in the graph, CIDR/IP, or http(s)/ssh URL."""
    if not isinstance(s, str) or not s:
        return False
    if s in hosts:
        return True
    try:
        ipaddress.ip_network(s, strict=False)
        return True
    except ValueError:
        pass
    return s.startswith(("http://", "https://", "ssh://"))

def check_pentest(g, name, p, errs):
    """Operator-authorized testing of owned systems. Launch-test only in automation."""
    w = f"pentests.{name}"
    if p.get("launch_test_only") is not True:
        errs.append(f"{w}: launch_test_only must be true "
                    "(validate/start/healthcheck/stop only; never live scans or exploits in tests)")
    scope = p.get("scope")
    if not isinstance(scope, dict):
        errs.append(f"{w}.scope: expected mapping with allow and deny")
        scope = {}
    else:
        for k in ("allow", "deny"):
            if k not in scope:
                errs.append(f"{w}.scope: missing required '{k}' (empty list = nothing allowed)")
        for k in scope:
            if k not in ("allow", "deny"):
                errs.append(f"{w}.scope: unknown field {k!r}")
    allow, deny = scope.get("allow"), scope.get("deny")
    if not isinstance(allow, list) or not all(isinstance(x, str) and x for x in allow):
        errs.append(f"{w}.scope.allow: expected list of strings (may be empty = nothing allowed)")
        allow = []
    if not isinstance(deny, list) or not all(isinstance(x, str) and x for x in deny):
        errs.append(f"{w}.scope.deny: expected list of strings (may be empty)")
        deny = []
    hosts = g.get("hosts") or {}
    for t in allow + deny:
        if not _scope_target_ok(t, hosts):
            errs.append(f"{w}.scope: target {t!r} is not a graph host name, CIDR/IP, or URL "
                        "(http://, https://, or ssh://)")
    overlap = sorted(set(allow) & set(deny))
    if overlap:
        errs.append(f"{w}.scope: targets in both allow and deny: {overlap}")
    tools = p.get("tools")
    if not isinstance(tools, dict):
        errs.append(f"{w}.tools: expected mapping with allow")
        tool_allow = []
    else:
        if "allow" not in tools:
            errs.append(f"{w}.tools: missing required 'allow' (empty list = no tools)")
        for k in tools:
            if k not in ("allow",):
                errs.append(f"{w}.tools: unknown field {k!r}")
        tool_allow = tools.get("allow")
        if not isinstance(tool_allow, list) or not all(isinstance(x, str) and x for x in tool_allow):
            errs.append(f"{w}.tools.allow: expected list of tool name strings (may be empty); no wildcards")
            tool_allow = []
        for t in tool_allow:
            if any(c in t for c in "*?[]") or t.lower() in ("*", "all", "any"):
                errs.append(f"{w}.tools.allow: wildcard {t!r} rejected; list tools by exact name")
    needs = [t for t in tool_allow
             if t in PENTEST_NETWORK_EXEC_TOOLS or t.split(".", 1)[0] in PENTEST_NETWORK_EXEC_TOOLS]
    if needs and not allow:
        errs.append(f"{w}: tools {needs} need network/exec scope but scope.allow is empty")
    if p.get("status") == "active":
        if not allow:
            errs.append(f"{w}: status active requires non-empty scope.allow "
                        "(empty = nothing allowed; refuse to launch)")
        if p.get("requires_operator_confirm") is not True:
            errs.append(f"{w}: status active requires requires_operator_confirm: true "
                        "(operator-authorized testing of owned systems only)")
        node = lookup(g, "nodes", p.get("node"))
        if node is not None:
            m = lookup(g, "models", node.get("model"))
            if m is not None and m.get("role") != "pentest":
                errs.append(f"{w}: active pentest node {p.get('node')!r} model role is "
                            f"{m.get('role')!r}; expected role pentest")

def check_kv_channel(g, name, c, errs):
    """C2C stage 1 (#22): slot KV file shipped between same-model nodes. Both ends must match
    model (same entry => same sha256), runtime build, per-slot ctx and kv_type."""
    a, b = lookup(g, "nodes", c.get("from")), lookup(g, "nodes", c.get("to"))
    if a is None or b is None: return
    w = f"kv_channels.{name}"
    if c.get("from") == c.get("to"): errs.append(f"{w}: from and to are the same node")
    if c.get("status") == "planned": return   # like planned nodes: schema-checked only
    ma, mb = lookup(g, "models", a.get("model")), lookup(g, "models", b.get("model"))
    if ma is not None and mb is not None:
        if ma.get("sha256") != mb.get("sha256"): errs.append(f"{w}: model sha256 differs ({ma.get('sha256')} vs {mb.get('sha256')})")
        elif ma.get("sha256") == "unmeasured" and c.get("status") != "planned":
            errs.append(f"{w}: model sha256 unmeasured; a non-planned kv channel needs a measured sha256 on both ends")
    ra, rb = lookup(g, "runtimes", a.get("runtime")), lookup(g, "runtimes", b.get("runtime"))
    if ra is not None and rb is not None and (ra.get("build"), ra.get("commit")) != (rb.get("build"), rb.get("commit")):
        errs.append(f"{w}: runtime build differs ({ra.get('build')} vs {rb.get('build')}); slot files are build-specific")
    if slot_ctx(a) != slot_ctx(b): errs.append(f"{w}: per-slot ctx differs ({slot_ctx(a)} vs {slot_ctx(b)})")
    if a.get("kv_type") != b.get("kv_type"): errs.append(f"{w}: kv_type differs ({a.get('kv_type')} vs {b.get('kv_type')})")

OPTION_ROLES = {"chat", "coder", "reasoning", "embed", "vision", "diffusion", "pentest", "decision", "stt", "tts"}
GPU_CANDIDATE_HOSTS = {"qodesh"}  # 8600 GT always-on role (feat/qodesh-legacy-gpu)

def check_option(g, name, o, errs):
    """Unplaced model options: a catalog, never placed. Nothing here is read by placement."""
    w = f"options.{name}"
    if o.get("unverified") is not True and not o.get("hf_repo"):
        errs.append(f"{w}: verified option needs hf_repo (otherwise keep unverified: true)")
    if o.get("gpu_candidate") is not None:
        if o.get("role") != "decision": errs.append(f"{w}: gpu_candidate is only for role decision (always-on GPU role, #24)")
        gh = o.get("gpu_host")
        if o.get("gpu_candidate") is True and gh not in GPU_CANDIDATE_HOSTS:
            errs.append(f"{w}: gpu_candidate true needs gpu_host in {sorted(GPU_CANDIDATE_HOSTS)}")
    for h in o.get("candidate_hosts") or []:
        if h not in (g.get("hosts") or {}): errs.append(f"{w}.candidate_hosts: no such host {h!r}")
    for n, nd in (g.get("models") or {}).items():
        if n == name: errs.append(f"{w}: same name as a placed model entry; promote by moving it to models, not both")

# ---- registry --------------------------------------------------------------
class T:
    def __init__(self, fields, check=None, experimental=False, doc=""):
        self.fields, self.check, self.experimental, self.doc = fields, check, experimental, doc

TYPES = {
    "hosts": T({"kind": req("enum", choices={"desktop", "laptop", "phone", "vm", "unknown"}),
                "measured": req("bool"), "os": opt("str"), "cpu": opt("str"), "threads": opt("int", min=1),
                "ram_mib": opt("int", min=1), "gpus": req("gpus"),
                "reserve_ram_mib": opt("int", min=0), "notes": opt("str"), "reported": opt("any"),
                "windows": opt("any"),
                # reachability for meshes (transport PoC, #22); key-only, never a password
                "addr": opt("str"), "user": opt("str"), "port": opt("int", min=1)}, check_host, doc="physical/virtual machine"),
    "transports": T({"kind": req("enum", choices={"local", "ssh", "nfs", "rsync", "bittorrent", "zfs"}),
                     "from": req("ref", ref="hosts"), "to": req("ref", ref="hosts")}, check_transport, doc="host-to-host link"),
    # Multi-member transports (ssh nexus hub, private bittorrent swarm). Point-to-point
    # links stay in transports:. Detailed checks live in scripts/transport_graph.py.
    "meshes": T({"type": req("enum", choices={"ssh", "bittorrent"}), "members": req("refs", ref="hosts"),
                 "hub": opt("str"), "root": opt("str"), "identity": opt("str"), "host_key_policy": opt("str"),
                 "tracker": opt("str"), "bind": opt("str"), "port": opt("int", min=1), "private": opt("bool"),
                 "client": opt("str")}, doc="multi-member transport (ssh nexus / bittorrent swarm)"),
    "runtimes": T({"kind": req("enum", choices={"llama-server", "drex-dlm", "sm11-legacy"}), "build": req("str"), "commit": req("str"),
                   "hosts": req("refs", ref="hosts"), "supported_archs": req("list"),
                   "backends": req("list"), "spec_types": req("strlist"), "bin": opt("str")}, check_runtime, doc="inference engine build"),
    "models": T({"gguf": req("str"), "sha256": req("sha"), "arch": req("str"), "trained_ctx": req("int", min=1),
                 "role": req("enum", choices={"chat", "coder", "decision", "reasoning", "embed", "vision", "diffusion", "pentest"}),
                 "derived_from": opt("any")}, doc="weights file"),  # derived_from: written by scripts/scale_down.py
    "nodes": T({"model": req("ref", ref="models"), "host": req("ref", ref="hosts"), "runtime": req("ref", ref="runtimes"),
                "ctx": req("int", min=1), "parallel": req("int", min=1),
                "kv_type": req("enum", choices={"f16", "bf16", "q8_0", "q4_0", "f32"}), "flash_attn": req("bool"),
                "offload": req("any"), "bind": req("str"), "port": req("int", min=1),
                "cache_ram_mib": req("int", min=0), "status": req("enum", choices={"active", "planned"}),
                "embeddings": opt("bool"), "scale_down": opt("any")}, check_node, doc="model instance on host+runtime"),
    "speculative": T({"experimental": req("bool"), "status": req("enum", choices={"planned", "experimental", "active"}),
                      "mode": req("enum", choices={"draft", "ngram"}), "target": req("ref", ref="nodes"),
                      "spec_type": opt("enum", choices=SPEC_TYPES), "draft": opt("ref", ref="models"),
                      "draft_max": opt("int", min=1), "draft_min": opt("int", min=0), "p_min": opt("num"),
                      "draft_ctx": opt("int", min=1), "draft_kv_type": opt("enum", choices={"f16", "bf16", "q8_0", "q4_0", "f32"}),
                      "draft_ngl": opt("int", min=0), "notes": opt("str")},
                     check_speculative, experimental=True,
                     doc="edge draft->target (same vocab) or model-free n-gram lookup decoding"),
    "gateways": T({"kind": req("enum", choices={"green-roomz"}), "host": req("ref", ref="hosts"),
                   "port": req("int", min=1)}, doc="router exposing aliases"),
    "aliases": T({"node": req("ref", ref="nodes"), "gateway": req("ref", ref="gateways")}, check_alias,
                 doc="route name -> exactly one node"),
    "agents": T({"kind": req("enum", choices={"hermes-agent"}), "host": req("ref", ref="hosts"),
                 "min_ctx": req("int", min=1), "context_length": req("int", min=1), "aliases": req("map")},
                check_agent, doc="agent process"),
    "fleets": T({"repo": req("str"), "agents": req("refs", ref="agents")}, doc="green-agentz agent group"),
    "agencies": T({"repo": req("str"), "labels": req("list"), "assignments": req("map")}, check_agency,
                  doc="GitHub-style issue workflow (not the retired green-agency repo)"),
    "rooms": T({"experimental": req("bool"), "gateway": req("ref", ref="gateways"), "agents": req("refs", ref="agents")},
               experimental=True, doc="shared conversation space"),
    "swarms": T({"experimental": req("bool"), "rooms": req("refs", ref="rooms")}, experimental=True, doc="set of rooms"),
    "stores": T({"experimental": req("bool"), "kind": req("enum", choices={"fs", "sqlite", "git"}),
                 "host": req("ref", ref="hosts"), "path": req("str")}, experimental=True, doc="persistent state"),
    "reaches": T({"experimental": req("bool"), "repo": req("str"), "agents": req("refs", ref="agents")},
                 experimental=True, doc="agent-reach tool bundle"),
    "councils": T({"experimental": req("bool"), "mode": req("enum", choices={"quorum", "cascade"}),
                   "agents": req("refs", ref="agents"), "quorum": opt("int")}, check_council, experimental=True,
                  doc="multi-agent decision (quorum N-of-M or ordered cascade)"),
    "pentests": T({"name": req("str"),
                   "node": req("ref", ref="nodes"),
                   "agent": req("ref", ref="agents"),
                   "scope": req("any"),
                   "tools": req("any"),
                   "report_to": req("ref", ref="agencies"),
                   "requires_operator_confirm": req("bool"),
                   "launch_test_only": req("bool"),
                   "status": req("enum", choices={"planned", "active"}),
                   "notes": opt("str")},
                  check_pentest,
                  doc="authorized testing of the owner's fleet (launch-test only in automation; not attack tooling)"),
    "kv_channels": T({"experimental": req("bool"), "status": req("enum", choices={"planned", "experimental", "active"}),
                      "from": req("ref", ref="nodes"), "to": req("ref", ref="nodes"),
                      "via": req("enum", choices={"local", "nexus", "bt"}), "transport": opt("str"),
                      "slot": opt("int", min=0), "notes": opt("str")},
                     check_kv_channel, experimental=True,
                     doc="C2C stage 1 edge: llama-server slot save/restore file shipped between same-model nodes (#22)"),

    "options": T({"role": req("enum", choices=OPTION_ROLES), "unverified": req("bool"), "sources": req("list"),
                  "hf_repo": opt("str", nullable=True), "size_note": opt("str"), "placement_note": opt("str"),
                  "candidate_hosts": opt("strlist"), "gpu_candidate": opt("bool"), "gpu_host": opt("str"),
                  "runtime_note": opt("str"), "notes": opt("str")},
                 check_option, doc="unplaced model option (catalog only; never placed or RAM-counted)"),
}
REQUIRED_SECTIONS = ("hosts", "runtimes", "models", "nodes", "gateways", "aliases", "agents")

def validate_types(g):
    errs = []
    if not isinstance(g, dict): return ["graph: top level must be a mapping"]
    if g.get("version") != 2: errs.append(f"version: expected 2 (typed schema), got {g.get('version')!r}")
    for sec in g:
        if sec != "version" and not str(sec).startswith("_") and sec not in TYPES: errs.append(f"{sec}: unknown section (registered types: {sorted(TYPES)})")
    for sec in REQUIRED_SECTIONS:
        if not g.get(sec): errs.append(f"{sec}: required section missing or empty")
    for sec, t in TYPES.items():
        items = g.get(sec) or {}
        if not isinstance(items, dict): errs.append(f"{sec}: expected mapping of name -> {sec[:-1]}"); continue
        for name, item in items.items():
            if not isinstance(item, dict): errs.append(f"{sec}.{name}: expected mapping"); continue
            for key in item:
                if key not in t.fields: errs.append(f"{sec}.{name}: unknown field {key!r}")
            for key, spec in t.fields.items():
                if key not in item:
                    if not spec.optional: errs.append(f"{sec}.{name}: missing required '{key}' (no defaults)")
                    continue
                check_field(g, sec, name, key, spec, item[key], errs)
            if t.experimental and item.get("experimental") is not True:
                errs.append(f"{sec}.{name}: experimental type; set 'experimental: true' to acknowledge")
            if t.check: t.check(g, name, item, errs)
    return errs
