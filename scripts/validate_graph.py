#!/usr/bin/env python3
"""Validate familia graph.yaml against GGUF metadata, hardware and agent needs.

Exit 0 when valid, 1 with one line per problem otherwise. With --args NODE,
print the llama-server arguments for that node. Never guesses or inflates.
"""
import os, struct, sys
import yaml

KV_BYTES = {"f16": 2.0, "bf16": 2.0, "q8_0": 1.0625, "q4_0": 0.5625, "f32": 4.0}

def gguf_meta(path):
    """Minimal GGUF v2/v3 metadata reader (stdlib only)."""
    out = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("not a GGUF file")
        ver, = struct.unpack("<I", f.read(4))
        if ver < 2:
            raise ValueError(f"unsupported GGUF version {ver}")
        _, n_kv = struct.unpack("<QQ", f.read(16))
        fmt = {0:"<B",1:"<b",2:"<H",3:"<h",4:"<I",5:"<i",6:"<f",7:"<?",10:"<Q",11:"<q",12:"<d"}
        def rstr():
            n, = struct.unpack("<Q", f.read(8)); return f.read(n).decode("utf-8", "replace")
        def rval(t):
            if t == 8: return rstr()
            if t == 9:
                et, n = struct.unpack("<IQ", f.read(12))
                if et in fmt and et != 8:
                    f.seek(struct.calcsize(fmt[et]) * n, 1); return None
                for _ in range(n): rval(et)
                return None
            s = fmt[t]; return struct.unpack(s, f.read(struct.calcsize(s)))[0]
        for _ in range(n_kv):
            k = rstr(); t, = struct.unpack("<I", f.read(4)); out[k] = rval(t)
    return out

def mem_total_mib():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    raise RuntimeError("cannot read MemTotal")

def kv_mib(meta, arch, ctx, kv_type):
    g = lambda k: meta.get(f"{arch}.{k}")
    layers, heads_kv, emb, heads = g("block_count"), g("attention.head_count_kv"), g("embedding_length"), g("attention.head_count")
    if not all(isinstance(x, int) and x for x in (layers, heads_kv, emb, heads)):
        return None
    head_dim = g("attention.key_length") or emb // heads
    # Hybrid models (e.g. qwen35) keep KV only on every Nth full-attention
    # layer; the rest carry a small fixed recurrent state.
    interval = g("full_attention_interval")
    attn_layers = -(-layers // interval) if isinstance(interval, int) and interval > 1 else layers
    kv = 2 * attn_layers * heads_kv * head_dim * ctx * KV_BYTES[kv_type]
    ssm_inner, ssm_state = g("ssm.inner_size"), g("ssm.state_size")
    if isinstance(ssm_inner, int) and isinstance(ssm_state, int):
        kv += (layers - attn_layers) * ssm_inner * ssm_state * 4  # f32 recurrent state
    return kv / 2**20

def validate(graph):
    errs, host = [], graph.get("host", {})
    nodes, total = graph.get("nodes") or {}, 0.0
    if not nodes: errs.append("graph has no nodes")
    ports = {}
    for name, n in nodes.items():
        for key in ("model", "arch", "ctx", "parallel", "kv_type", "port", "aliases", "cache_ram_mib"):
            if key not in n: errs.append(f"node {name}: missing required '{key}' (no defaults)")
        if any(k not in n for k in ("model", "arch", "ctx", "parallel", "kv_type", "port")): continue
        path = os.path.expanduser(n["model"])
        if n["port"] in ports: errs.append(f"node {name}: port {n['port']} also used by {ports[n['port']]}")
        ports[n["port"]] = name
        if n["kv_type"] not in KV_BYTES: errs.append(f"node {name}: unknown kv_type {n['kv_type']}")
        if not os.path.isfile(path):
            errs.append(f"node {name}: model file not found: {path}"); continue
        try: meta = gguf_meta(path)
        except Exception as e: errs.append(f"node {name}: cannot read GGUF: {e}"); continue
        arch = meta.get("general.architecture")
        if arch != n["arch"]: errs.append(f"node {name}: GGUF architecture is {arch!r}, graph says {n['arch']!r}")
        train = meta.get(f"{arch}.context_length")
        if isinstance(train, int) and n["ctx"] // n["parallel"] > train:
            errs.append(f"node {name}: per-slot ctx {n['ctx'] // n['parallel']} exceeds model's trained context {train}")
        kv = kv_mib(meta, arch, n["ctx"], n["kv_type"]) if n["kv_type"] in KV_BYTES else None
        # Prompt-cache state for one full slot is roughly that slot's KV; if
        # --cache-ram is smaller, llama.cpp skips caching on every request.
        state = kv_mib(meta, arch, n["ctx"] // n["parallel"], n["kv_type"]) if n["kv_type"] in KV_BYTES else None
        cache = n.get("cache_ram_mib")
        if state is not None and isinstance(cache, int) and cache < state:
            errs.append(f"node {name}: cache_ram_mib {cache} < estimated per-slot prompt state {state:.0f} MiB (prompt cache would always be skipped)")
        total += os.path.getsize(path) / 2**20 + (kv or 0) + 256 + (cache if isinstance(cache, int) else 0)
        n["_slot_ctx"] = n["ctx"] // n["parallel"]
    budget = mem_total_mib() - int(host.get("reserve_ram_mib", 2048))
    if total > budget: errs.append(f"estimated RAM {total:.0f} MiB exceeds budget {budget} MiB (MemTotal - reserve)")
    aliases = {a: k for k, n in nodes.items() for a in n.get("aliases", [])}
    for an, a in (graph.get("agents") or {}).items():
        for role, target in (a.get("edges") or {}).items():
            node = nodes.get(aliases.get(target, target))
            if node is None: errs.append(f"agent {an}: edge {role} -> {target}: no such node/alias"); continue
            if "context_length" not in a:
                errs.append(f"agent {an}: missing required 'context_length' (must equal node per-slot ctx)")
            elif "_slot_ctx" in node and a["context_length"] != node["_slot_ctx"]:
                errs.append(f"agent {an}: context_length {a['context_length']} != node {target} per-slot ctx {node['_slot_ctx']} (larger makes llama.cpp silently truncate; smaller wastes the window)")
            if "_slot_ctx" in node and node["_slot_ctx"] < a.get("min_ctx", 0):
                errs.append(f"agent {an}: edge {role} -> {target}: per-slot ctx {node['_slot_ctx']} < agent min_ctx {a['min_ctx']}")
    return errs, total

def server_args(n):
    a = ["-m", os.path.expanduser(n["model"]), "--host", n.get("host", "127.0.0.1"), "--port", str(n["port"]),
         "-c", str(n["ctx"]), "-np", str(n["parallel"]), "-ctk", n["kv_type"], "-ctv", n["kv_type"],
         "-ngl", str(n.get("gpu_layers", 0)), "--jinja"]
    if n.get("flash_attn"): a += ["-fa", "on"]
    for al in n.get("aliases", [])[:1]: a += ["--alias", al]
    a += ["--cache-ram", str(n["cache_ram_mib"])]
    return a

def main(argv):
    path = "graph.yaml"
    if "--graph" in argv: path = argv[argv.index("--graph") + 1]
    graph = yaml.safe_load(open(path))
    errs, total = validate(graph)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from transport_graph import validate_transports
    errs += validate_transports(graph)
    for e in errs: print(f"graph: ERROR: {e}", file=sys.stderr)
    if errs: return 1
    if "--args" in argv:
        print(" ".join(server_args(graph["nodes"][argv[argv.index("--args") + 1]]))); return 0
    print(f"graph: OK ({len(graph['nodes'])} node(s), est. {total:.0f} MiB)")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
