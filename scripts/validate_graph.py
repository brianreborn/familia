#!/usr/bin/env python3
"""Validate familia graph.yaml against GGUF metadata, hardware and agent needs.

Exit 0 when valid, 1 with one line per problem otherwise. With --args NODE,
print the llama-server arguments for that node. Never guesses or inflates.
--no-files skips GGUF/RAM checks (schema only); --verify-sha hashes GGUFs.
Schema: scripts/graph_types.py, docs/graph-types.md.
"""
import hashlib, os, struct, sys
import yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graph_types import validate_types, TYPES  # noqa: E402

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
                    f.seek(struct.calcsize(fmt[et]) * n, 1); return ("array", n, None)
                h = hashlib.sha256() if et == 8 else None
                for _ in range(n):
                    v = rval(et)
                    if h is not None: h.update(v.encode() + b"\0")
                return ("array", n, h.hexdigest() if h else None)
            s = fmt[t]; return struct.unpack(s, f.read(struct.calcsize(s)))[0]
        for _ in range(n_kv):
            k = rstr(); t, = struct.unpack("<I", f.read(4)); out[k] = rval(t)
    return out

def vocab(meta):
    """(tokenizer model, n_vocab, sha256 of the token list) from GGUF metadata."""
    t = meta.get("tokenizer.ggml.tokens")
    n, h = (t[1], t[2]) if isinstance(t, tuple) else (None, None)
    return meta.get("tokenizer.ggml.model"), n, h

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

class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys: a second alias/node with the same name must not silently win."""
    def construct_mapping(self, node, deep=False):
        seen = set()
        for k, _ in node.value:
            key = self.construct_object(k, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", k.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep)

def load(path):
    with open(path) as f:
        return yaml.load(f, Loader=UniqueKeyLoader)

def validate(graph, check_files=True):
    """Typed schema check, then GGUF/RAM checks. Returns (errors, {host: est MiB})."""
    errs = validate_types(graph)
    if errs or not check_files:
        return errs, {}
    hosts, models, totals = graph["hosts"], graph["models"], {}
    base = os.path.dirname(os.path.abspath(graph.get("_path", "graph.yaml")))
    for rn, r in graph["runtimes"].items():
        if "bin" in r and "--check-runtimes" in sys.argv:
            b = os.path.join(base, os.path.expanduser(r["bin"]))
            if not os.access(b, os.X_OK): errs.append(f"runtimes.{rn}: binary not executable: {b}"); continue
            import subprocess
            v = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=30)
            if str(r["commit"])[:9] not in v.stdout + v.stderr: errs.append(f"runtimes.{rn}: {b} does not report commit {r['commit']}")
    metas = {}
    for name, n in graph["nodes"].items():
        if n["status"] == "planned": continue
        m = models[n["model"]]
        path = os.path.expanduser(m["gguf"])
        if not os.path.isfile(path):
            errs.append(f"nodes.{name}: model file not found: {path}"); continue
        try: meta = gguf_meta(path)
        except Exception as e: errs.append(f"nodes.{name}: cannot read GGUF: {e}"); continue
        arch = meta.get("general.architecture")
        if arch != m["arch"]: errs.append(f"models.{n['model']}: GGUF architecture is {arch!r}, graph says {m['arch']!r}")
        train = meta.get(f"{arch}.context_length")
        if isinstance(train, int) and train != m["trained_ctx"]:
            errs.append(f"models.{n['model']}: trained_ctx {m['trained_ctx']} but GGUF says {train}")
        if m["sha256"] != "unmeasured" and "--verify-sha" in sys.argv:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
            if h.hexdigest() != m["sha256"]: errs.append(f"models.{n['model']}: sha256 mismatch ({h.hexdigest()})")
        metas[name] = meta
        kv = kv_mib(meta, arch, n["ctx"], n["kv_type"])
        layers = meta.get(f"{arch}.block_count")
        ngl = n["offload"]["ngl"]
        if ngl and isinstance(layers, int):
            gp = hosts[n["host"]]["gpus"][n["offload"]["main_gpu"]]
            frac = min(ngl, layers + 1) / (layers + 1)
            need = frac * (os.path.getsize(path) / 2**20 + (kv or 0)) + n["offload"].get("vram_reserve_mib", 0)
            if isinstance(gp.get("vram_mib"), int) and need > gp["vram_mib"]:
                errs.append(f"nodes.{name}: offload ngl {ngl} needs ~{need:.0f} MiB VRAM > GPU {n['offload']['main_gpu']} vram_mib {gp['vram_mib']}")
        # Prompt-cache state for one full slot is roughly that slot's KV; if
        # --cache-ram is smaller, llama.cpp skips caching on every request.
        state = kv_mib(meta, arch, n["ctx"] // n["parallel"], n["kv_type"])
        if n.get("embeddings"): state = None  # embedding servers keep no prompt cache
        if state is not None and n["cache_ram_mib"] < state:
            errs.append(f"nodes.{name}: cache_ram_mib {n['cache_ram_mib']} < estimated per-slot prompt state {state:.0f} MiB (prompt cache would always be skipped)")
        totals[n["host"]] = totals.get(n["host"], 0.0) + os.path.getsize(path) / 2**20 + (kv or 0) + 256 + n["cache_ram_mib"]
    for sn, sp in (graph.get("speculative") or {}).items():
        t = graph["nodes"][sp["target"]]
        if t["status"] == "planned" or sp["mode"] != "draft" or sp["target"] not in metas: continue
        d = models[sp["draft"]]; dp = os.path.expanduser(d["gguf"])
        if not os.path.isfile(dp): errs.append(f"speculative.{sn}: draft file not found: {dp}"); continue
        dmeta = gguf_meta(dp)
        tv, dv = vocab(metas[sp["target"]]), vocab(dmeta)
        if tv != dv or None in tv:
            errs.append(f"speculative.{sn}: tokenizer/vocab mismatch target {tv[:2]} hash {str(tv[2])[:12]} vs draft {dv[:2]} hash {str(dv[2])[:12]}")
        dctx = sp.get("draft_ctx", t["ctx"])
        dkv = kv_mib(dmeta, dmeta.get("general.architecture"), dctx, sp.get("draft_kv_type", t["kv_type"])) or 0
        totals[t["host"]] = totals.get(t["host"], 0.0) + os.path.getsize(dp) / 2**20 + dkv  # draft weights + its KV
    for h, total in totals.items():
        # RAM safety (docs/ram-safety.md): estimated_used + reserve must fit total_ram.
        ram = hosts[h]["ram_mib"]
        reserve = hosts[h]["reserve_ram_mib"]
        if total + reserve > ram:
            errs.append(
                f"hosts.{h}: estimated RAM {total:.0f} MiB + reserve {reserve} MiB exceeds ram_mib {ram} MiB"
            )
        free_after = ram - total
        if ram < 8192 and free_after < 2048:
            errs.append(
                f"hosts.{h}: estimated free after nodes {free_after:.0f} MiB < 2048 MiB floor "
                f"on host with ram_mib {ram} < 8192 (OOM safety; see docs/ram-safety.md)"
            )
    return errs, totals

def server_args(graph, name):
    n = graph["nodes"][name]
    m = graph["models"][n["model"]]
    a = ["-m", os.path.expanduser(m["gguf"]), "--host", n["bind"], "--port", str(n["port"]),
         "-c", str(n["ctx"]), "-np", str(n["parallel"]), "-ctk", n["kv_type"], "-ctv", n["kv_type"],
         "-ngl", str(n["offload"]["ngl"]), "--jinja"]
    if n["offload"]["ngl"]: a += ["-sm", n["offload"]["split"], "-mg", str(n["offload"]["main_gpu"])]
    if n["flash_attn"]: a += ["-fa", "on"]
    names = sorted(al for al, x in graph["aliases"].items() if x["node"] == name)
    if names: a += ["--alias", names[0]]
    a += ["--cache-ram", str(n["cache_ram_mib"])]
    if n.get("embeddings"): a += ["--embeddings"]
    # Speculative flags verified against b11374/b11539 --help; --draft-max/--draft-min were removed upstream.
    for sp in (graph.get("speculative") or {}).values():
        if sp["target"] != name or sp["status"] == "planned": continue
        if sp["mode"] == "draft":
            a += ["-md", os.path.expanduser(graph["models"][sp["draft"]]["gguf"]), "--spec-type", sp.get("spec_type", "draft-simple"),
                  "--spec-draft-n-max", str(sp["draft_max"]), "--spec-draft-n-min", str(sp["draft_min"]),
                  "--spec-draft-p-min", str(sp["p_min"]), "-ngld", str(sp.get("draft_ngl", 0))]
            if "draft_kv_type" in sp: a += ["-ctkd", sp["draft_kv_type"], "-ctvd", sp["draft_kv_type"]]
        else:
            a += ["--spec-type", sp["spec_type"]]
    r = graph["runtimes"][n["runtime"]]
    if "bin" in r:
        a = [os.path.join(os.path.dirname(os.path.abspath(graph.get("_path", "graph.yaml"))), r["bin"])] + a
    return a

def main(argv):
    path = "graph.yaml"
    if "--graph" in argv: path = argv[argv.index("--graph") + 1]
    try: graph = load(path); graph["_path"] = path
    except yaml.YAMLError as e:
        print(f"graph: ERROR: {e}", file=sys.stderr); return 1
    errs, totals = validate(graph, check_files="--no-files" not in argv)
    for e in errs: print(f"graph: ERROR: {e}", file=sys.stderr)
    if errs: return 1
    if "--args" in argv:
        print(" ".join(server_args(graph, argv[argv.index("--args") + 1]))); return 0
    est = ", ".join(f"{h} est. {t:.0f} MiB" for h, t in totals.items()) or "file checks skipped"
    print(f"graph: OK ({len(graph['nodes'])} node(s); {est})")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
