"""Typed schema for the familia declarative graph (graph.yaml, version 2).

Every section of graph.yaml is a *type* registered in TYPES.  A type is a
field spec (required fields, no defaults) plus an optional cross-check
function.  Adding a refined or new type = one TYPES entry + one checker.
See docs/graph-types.md.
"""
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
    elif k == "map":
        if not isinstance(val, dict) or not val: errs.append(f"{where}: expected non-empty mapping")
    else:
        raise AssertionError(k)

# ---- cross-checks ----------------------------------------------------------
def lookup(g, sec, key):
    """Entry `key` of section `sec`, or None (also for malformed, unhashable keys)."""
    return (g.get(sec) or {}).get(key) if isinstance(key, str) else None

HOST_FACTS = ("os", "cpu", "threads", "ram_mib", "gpu", "vram_mib", "reserve_ram_mib")

def check_host(g, name, h, errs):
    if h.get("measured") is True:
        for k in HOST_FACTS:
            if k not in h: errs.append(f"hosts.{name}: measured host missing required '{k}'")
        if h.get("kind") == "unknown": errs.append(f"hosts.{name}: measured host cannot have kind 'unknown'")
        if isinstance(h.get("ram_mib"), int) and isinstance(h.get("reserve_ram_mib"), int) and h["reserve_ram_mib"] >= h["ram_mib"]:
            errs.append(f"hosts.{name}: reserve_ram_mib >= ram_mib leaves nothing for nodes")
    elif h.get("measured") is False:
        for k in ("threads", "ram_mib", "vram_mib", "reserve_ram_mib"):
            if k in h: errs.append(f"hosts.{name}: '{k}' given but measured is false; record only measured facts (set measured: true)")

def check_transport(g, name, t, errs):
    if t.get("kind") == "local" and t.get("from") != t.get("to"):
        errs.append(f"transports.{name}: kind local requires from == to")
    if t.get("kind") != "local" and t.get("from") == t.get("to"):
        errs.append(f"transports.{name}: kind {t.get('kind')} links a host to itself; use kind local")

def check_runtime(g, name, r, errs):
    if r.get("kind") == "llama-server":
        c = r.get("commit")
        if isinstance(c, str) and not re.match(r"^[0-9a-f]{7,40}$", c):
            errs.append(f"runtimes.{name}: commit {c!r} is not a git sha (a branch name is not a pin)")

def slot_ctx(n):
    return n["ctx"] // n["parallel"] if isinstance(n.get("ctx"), int) and isinstance(n.get("parallel"), int) and n["parallel"] > 0 else None

def check_node(g, name, n, errs):
    h, r, m = lookup(g, "hosts", n.get("host")), lookup(g, "runtimes", n.get("runtime")), lookup(g, "models", n.get("model"))
    if h is not None and h.get("measured") is not True:
        errs.append(f"nodes.{name}: host {n['host']!r} is not measured; unmeasured hosts are excluded from placement")
    if r is not None and n.get("host") not in (r.get("hosts") or []):
        errs.append(f"nodes.{name}: runtime {n['runtime']!r} is not installed on host {n.get('host')!r} (runtime hosts: {r.get('hosts')})")
    if r is not None and m is not None and m.get("arch") not in (r.get("supported_archs") or []):
        errs.append(f"nodes.{name}: model {n['model']!r} arch {m.get('arch')!r} not in runtime {n['runtime']!r} "
                    f"(build {r.get('build')}) supported_archs {r.get('supported_archs')}; upgrade the runtime pin, do not drop the model")
    if isinstance(n.get("ctx"), int) and isinstance(n.get("parallel"), int) and n["parallel"] > 0 and n["ctx"] % n["parallel"]:
        errs.append(f"nodes.{name}: ctx {n['ctx']} not divisible by parallel {n['parallel']}")
    s = slot_ctx(n)
    if m is not None and s is not None and isinstance(m.get("trained_ctx"), int) and s > m["trained_ctx"]:
        errs.append(f"nodes.{name}: per-slot ctx {s} exceeds model trained_ctx {m['trained_ctx']} (no inflation)")
    if h is not None and isinstance(n.get("gpu_layers"), int) and n["gpu_layers"] > 0 and h.get("vram_mib") == 0:
        errs.append(f"nodes.{name}: gpu_layers {n['gpu_layers']} but host {n['host']!r} has vram_mib 0")
    for other, o in (g.get("nodes") or {}).items():
        if other < name and o.get("host") == n.get("host") and o.get("port") == n.get("port"):
            errs.append(f"nodes.{name}: port {n.get('port')} on host {n.get('host')!r} also used by node {other!r}")

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

# ---- registry --------------------------------------------------------------
class T:
    def __init__(self, fields, check=None, experimental=False, doc=""):
        self.fields, self.check, self.experimental, self.doc = fields, check, experimental, doc

TYPES = {
    "hosts": T({"kind": req("enum", choices={"desktop", "laptop", "phone", "vm", "unknown"}),
                "measured": req("bool"), "os": opt("str"), "cpu": opt("str"), "threads": opt("int", min=1),
                "ram_mib": opt("int", min=1), "gpu": opt("str", nullable=True), "vram_mib": opt("int", min=0),
                "reserve_ram_mib": opt("int", min=0), "notes": opt("str")}, check_host, doc="physical/virtual machine"),
    "transports": T({"kind": req("enum", choices={"local", "ssh", "nfs", "rsync", "bittorrent", "zfs"}),
                     "from": req("ref", ref="hosts"), "to": req("ref", ref="hosts")}, check_transport, doc="host-to-host link"),
    "runtimes": T({"kind": req("enum", choices={"llama-server", "drex-dlm"}), "build": req("str"), "commit": req("str"),
                   "hosts": req("refs", ref="hosts"), "supported_archs": req("list")}, check_runtime, doc="inference engine build"),
    "models": T({"gguf": req("str"), "sha256": req("sha"), "arch": req("str"), "trained_ctx": req("int", min=1),
                 "role": req("enum", choices={"chat", "coder", "reasoning", "embed", "vision", "diffusion"})}, doc="weights file"),
    "nodes": T({"model": req("ref", ref="models"), "host": req("ref", ref="hosts"), "runtime": req("ref", ref="runtimes"),
                "ctx": req("int", min=1), "parallel": req("int", min=1),
                "kv_type": req("enum", choices={"f16", "bf16", "q8_0", "q4_0", "f32"}), "flash_attn": req("bool"),
                "gpu_layers": req("int", min=0), "bind": req("str"), "port": req("int", min=1),
                "cache_ram_mib": req("int", min=0)}, check_node, doc="model instance on host+runtime"),
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
}
REQUIRED_SECTIONS = ("hosts", "runtimes", "models", "nodes", "gateways", "aliases", "agents")

def validate_types(g):
    errs = []
    if not isinstance(g, dict): return ["graph: top level must be a mapping"]
    if g.get("version") != 2: errs.append(f"version: expected 2 (typed schema), got {g.get('version')!r}")
    for sec in g:
        if sec != "version" and sec not in TYPES: errs.append(f"{sec}: unknown section (registered types: {sorted(TYPES)})")
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
