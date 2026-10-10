#!/usr/bin/env python3
"""Optional, opt-in model scale-down for graph.yaml nodes (see docs/scale-down.md).

Only wraps existing published tooling; it never invents a compression method.
A node is processed only when it has `scale_down: {enabled: true, ...}`.

Backends (in order of preference):
  published       download an already-compressed GGUF published on Hugging Face
                  (e.g. an existing IQ1_S/IQ2_XXS quant) and verify its sha256.
  llama-quantize  run llama.cpp llama-quantize (optionally llama-imatrix first)
                  on the node's original GGUF.
  littlebit       Samsung LittleBit (arXiv 2506.13771, github.com/SamsungLabs/LittleBit).
                  TBD: its code is QAT (GPU training) on HF checkpoints and emits no
                  GGUF that llama.cpp can load, so this backend refuses to run.

The original model file is never written to. The output gets a sidecar
<output>.scale-down.json (sha256, backend, params, source sha256), and a derived
node `<name>-<suffix>` is written to a separate graph file (default
graph.scaled.yaml) with `derived_from:` so validate_graph.py can check it.
"""
import copy, hashlib, json, os, subprocess, sys, time, urllib.request
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_graph import gguf_meta  # noqa: E402

LOW_BIT_NEEDS_IMATRIX = {"IQ1_S", "IQ1_M", "IQ2_XXS", "IQ2_XS", "IQ2_S"}

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def fail(msg): raise SystemExit(f"scale_down: ERROR: {msg}")

def resolve(base, p): return os.path.join(base, os.path.expanduser(str(p)))

def backend_published(cfg, src, out, base):
    for k in ("repo", "file"):
        if k not in cfg: fail(f"published backend needs '{k}'")
    url = f"https://huggingface.co/{cfg['repo']}/resolve/{cfg.get('revision', 'main')}/{cfg['file']}"
    tmp = out + ".part"
    urllib.request.urlretrieve(url, tmp)
    got = sha256(tmp)
    if cfg.get("sha256") and got != cfg["sha256"]:
        os.remove(tmp); fail(f"sha256 mismatch for {url}: got {got}, expected {cfg['sha256']}")
    os.replace(tmp, out)
    return {"url": url, "revision": cfg.get("revision", "main"), "pinned_sha256": cfg.get("sha256")}

def backend_llama_quantize(cfg, src, out, base):
    qtype = cfg.get("type") or fail("llama-quantize backend needs 'type' (e.g. IQ2_XXS, Q2_K)")
    qbin = resolve(base, cfg.get("quantize_bin") or fail("llama-quantize backend needs 'quantize_bin'"))
    params = {"type": qtype, "quantize_bin": cfg["quantize_bin"]}
    imat = cfg.get("imatrix")
    if cfg.get("calibration"):
        ibin = resolve(base, cfg.get("imatrix_bin") or fail("'calibration' needs 'imatrix_bin'"))
        imat = out + ".imatrix.gguf"
        cmd = [ibin, "-m", src, "-f", resolve(base, cfg["calibration"]), "-o", imat,
               "-c", str(cfg.get("imatrix_ctx", 512)), "--chunks", str(cfg.get("imatrix_chunks", 32))]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode or not os.path.isfile(imat): fail(f"llama-imatrix failed: {r.stderr[-800:]}")
        params.update(calibration=cfg["calibration"], calibration_sha256=sha256(resolve(base, cfg["calibration"])),
                      imatrix_ctx=cfg.get("imatrix_ctx", 512), imatrix_chunks=cfg.get("imatrix_chunks", 32))
    elif imat:
        imat = resolve(base, imat)
    if qtype.upper() in LOW_BIT_NEEDS_IMATRIX and not imat:
        fail(f"type {qtype} needs an importance matrix: set 'imatrix' or 'calibration'")
    cmd = [qbin] + (["--imatrix", imat] if imat else []) + list(cfg.get("extra_args", [])) + \
          [src, out + ".part", qtype, str(cfg.get("threads", os.cpu_count() or 1))]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: fail(f"llama-quantize failed: {r.stderr[-800:]}")
    os.replace(out + ".part", out)
    if imat: params["imatrix_sha256"] = sha256(imat)
    params["extra_args"] = list(cfg.get("extra_args", []))
    return params

def backend_littlebit(cfg, src, out, base):
    fail("backend 'littlebit' is TBD: SamsungLabs/LittleBit is GPU QAT on HF checkpoints and produces "
         "no llama.cpp-loadable GGUF; use 'published' or 'llama-quantize'")

BACKENDS = {"published": backend_published, "llama-quantize": backend_llama_quantize, "littlebit": backend_littlebit}

def model_of(graph, node):
    """(gguf path, arch) for a node: schema v2 nodes name a models: entry, v1 nodes carry both."""
    if (graph.get("version") or 1) >= 2:
        m = graph["models"][node["model"]]; return m["gguf"], m["arch"]
    return node["model"], node["arch"]

def scale_node(name, node, base, force=False, graph=None):
    cfg = node["scale_down"]
    model_path, model_arch = model_of(graph or {}, node)
    backend = cfg.get("backend") or fail(f"node {name}: scale_down needs 'backend' ({', '.join(BACKENDS)})")
    if backend not in BACKENDS: fail(f"node {name}: unknown backend {backend!r}")
    src = resolve(base, model_path)
    out = resolve(base, cfg.get("output") or fail(f"node {name}: scale_down needs 'output' (explicit path)"))
    if os.path.realpath(out) == os.path.realpath(src): fail(f"node {name}: output must not be the original model")
    if not os.path.isfile(src) and backend != "published": fail(f"node {name}: model not found: {src}")
    if os.path.exists(out) and not force:
        fail(f"node {name}: {out} exists; refusing to overwrite (use --force to regenerate)")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    src_sha = sha256(src) if os.path.isfile(src) else None
    t0 = time.time()
    params = BACKENDS[backend](cfg, src, out, base)
    arch_out = gguf_meta(out).get("general.architecture")
    if arch_out != model_arch: fail(f"node {name}: output arch {arch_out!r} != model arch {model_arch!r}")
    rec = {"node": name, "backend": backend, "params": params, "source": model_path, "source_sha256": src_sha,
           "source_bytes": os.path.getsize(src) if src_sha else None, "output": cfg["output"],
           "output_sha256": sha256(out), "output_bytes": os.path.getsize(out), "arch": arch_out,
           "seconds": round(time.time() - t0, 1), "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if rec["source_bytes"] and rec["output_bytes"] >= rec["source_bytes"]:
        fail(f"node {name}: output ({rec['output_bytes']} B) is not smaller than source ({rec['source_bytes']} B)")
    json.dump(rec, open(out + ".scale-down.json", "w"), indent=2)
    return rec

def derived_node(name, node, rec):
    d = copy.deepcopy(node); cfg = d.pop("scale_down")
    d["model"] = cfg["output"]
    d["derived_from"] = {"node": name, "sha256": rec["output_sha256"], "manifest": cfg["output"] + ".scale-down.json"}
    d["port"] = cfg.get("port", node["port"])
    d["aliases"] = cfg.get("aliases", [f"{a}-{cfg.get('suffix', 'sd')}" for a in node.get("aliases", [])])
    return f"{name}-{cfg.get('suffix', 'sd')}", d

def derived_v2(graph, name, node, rec):
    """Schema v2: a new models: entry (with derived_from) plus a node serving it, and
    explicit top-level aliases. Nothing is auto-picked: port/suffix come from scale_down."""
    cfg = node["scale_down"]; sfx = cfg.get("suffix", "sd")
    mn = f"{node['model']}-{sfx}"
    m = copy.deepcopy(graph["models"][node["model"]])
    m.update(gguf=cfg["output"], sha256=rec["output_sha256"],
             derived_from={"model": node["model"], "sha256": rec["output_sha256"], "manifest": cfg["output"] + ".scale-down.json"})
    d = copy.deepcopy(node); d.pop("scale_down"); d["model"] = mn; d["port"] = cfg.get("port", node["port"])
    dn = f"{name}-{sfx}"
    al = {f"{a}-{sfx}": dict(x, node=dn) for a, x in (graph.get("aliases") or {}).items() if x.get("node") == name}
    return mn, m, dn, d, al

def main(argv):
    path = argv[argv.index("--graph") + 1] if "--graph" in argv else "graph.yaml"
    outg = argv[argv.index("--out-graph") + 1] if "--out-graph" in argv else os.path.join(os.path.dirname(path) or ".", "graph.scaled.yaml")
    only = argv[argv.index("--node") + 1] if "--node" in argv else None
    base = os.path.dirname(os.path.abspath(path))
    graph = yaml.safe_load(open(path))
    picked = {n: v for n, v in (graph.get("nodes") or {}).items()
              if (v.get("scale_down") or {}).get("enabled") is True and (only is None or n == only)}
    if not picked:
        print("scale_down: nothing to do (no node has scale_down.enabled: true)"); return 0
    if "--dry-run" in argv:
        for n, v in picked.items(): print(f"scale_down: would run {v['scale_down'].get('backend')} for {n} -> {v['scale_down'].get('output')}")
        return 0
    new = copy.deepcopy(graph)
    for n, v in picked.items():
        rec = scale_node(n, v, base, force="--force" in argv, graph=graph)
        if (graph.get("version") or 1) >= 2:
            mn, m, dn, d, al = derived_v2(graph, n, v, rec)
            new["models"][mn] = m; new["nodes"][dn] = d; new.setdefault("aliases", {}).update(al)
        else:
            dn, d = derived_node(n, v, rec)
            new["nodes"][dn] = d
        if "--replace" in argv: new["nodes"].pop(n)  # serve only the scaled copy; original file untouched
        print(f"scale_down: {n} -> {dn}: {rec['output_bytes']/2**20:.1f} MiB (from {(rec['source_bytes'] or 0)/2**20:.1f} MiB) sha256 {rec['output_sha256'][:12]}")
    for v in new["nodes"].values(): v.pop("scale_down", None)
    yaml.safe_dump(new, open(outg, "w"), sort_keys=False)
    print(f"scale_down: wrote {outg}; check it with scripts/validate_graph.py --graph {outg}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
