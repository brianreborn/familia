#!/usr/bin/env python3
"""familia model + hardware registry (docs/model-registry.md).

registry/records.jsonl  append-only measured results (one JSON object per line)
registry/hardware/*.yaml shareable hardware profiles (no hostnames/IPs/users)
registry/hosts.yaml      our host -> profile id

  registry.py add FILE.json|-          validate + append one record
  registry.py query [--host H] [--model SUBSTR] [--backend B]
  registry.py summarize
  registry.py suggest --host H --role decision|coder|embed [--graph graph.yaml]
  registry.py match [--measure-json F | --graph G --host H]
  registry.py power [--host H]
Never writes graph.yaml; suggest/match print snippets only.
"""
import argparse, datetime, glob, json, os, re, sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, "registry")
RECORDS = os.path.join(REG, "records.jsonl")
REQUIRED = ("host", "device", "runtime", "model", "settings", "metrics", "timestamp", "source")
ROLE_MODELS = {"decision": ("SmolLM2", "stories15M"), "coder": ("LFM2", "Qwen", "coder"), "embed": ("embed", "gemma-embedding")}
PRIVATE = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b|u0_a\d+|ssh-(ed25519|rsa)|BEGIN [A-Z ]*PRIVATE KEY")

def normalize(r):
    missing = [k for k in REQUIRED if k not in r]
    if missing: raise ValueError("record missing " + ", ".join(missing))
    for k, v in (r.get("metrics") or {}).items():
        if isinstance(v, dict) and ("min" in v or "value" in v) and "measured" not in v:
            raise ValueError(f"metrics.{k}: say measured: true|false (never implied)")
    r.setdefault("concurrency", None); r.setdefault("correctness", None)
    r.setdefault("power", {"measured": False, "watts": None})
    r.setdefault("schema", 1)
    return r

def append(r, path=RECORDS):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(r, sort_keys=True, ensure_ascii=True) + "\n")

def load(path=RECORDS):
    if not os.path.exists(path): return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]

def profiles():
    out = {}
    for p in sorted(glob.glob(os.path.join(REG, "hardware", "*.yaml"))):
        d = yaml.safe_load(open(p, encoding="utf-8")); out[d["id"]] = d
    return out

def host_map():
    p = os.path.join(REG, "hosts.yaml")
    return yaml.safe_load(open(p)) if os.path.exists(p) else {}

def tg(r):
    m = (r.get("metrics") or {}).get("tg_tps") or {}
    return m.get("min"), m.get("max")

def filt(recs, host=None, model=None, backend=None):
    for r in recs:
        if host and r["host"] != host: continue
        if model and model.lower() not in json.dumps(r["model"]).lower(): continue
        if backend and r["device"].get("backend") != backend: continue
        yield r

def power_w(prof, backend):
    """(watts, label) for a placement; estimates are labelled, never measured."""
    pw = (prof or {}).get("power") or {}
    if "gpu_board_w" in pw and backend not in ("cpu",):
        return pw["gpu_board_w"]["value"], "estimate: vendor max board power (upper bound)"
    if "package_tdp_w" in pw:
        return pw["package_tdp_w"]["value"], "estimate: package TDP (shared CPU+iGPU)"
    if "cpu_tdp_w" in pw:
        return pw["cpu_tdp_w"]["value"], "estimate: CPU TDP (upper bound)"
    iw = pw.get("inference_w") or {}
    if iw.get("estimate_w"):
        return iw["estimate_w"], "estimate: " + iw.get("method", "assumed")
    return None, "unknown"

def suggest(host, role, recs, graph=None):
    prof = profiles().get(host_map().get(host))
    keys = ROLE_MODELS[role]
    cands = []
    for r in filt(recs, host=host):
        name = json.dumps(r["model"])
        if not any(k.lower() in name.lower() for k in keys): continue
        lo, hi = tg(r)
        if lo is None: continue
        pen, why = 1.0, []
        c = r.get("concurrency")
        if not c:
            # contention: look for a concurrent record of the same device+model
            for o in filt(recs, host=host):
                oc = o.get("concurrency")
                if oc and o["device"] == r["device"] and o["model"] == r["model"] and tg(o)[0]:
                    pen = min(pen, tg(o)[0] / lo); why.append(f"measured contention x{tg(o)[0]/lo:.2f} with {oc['co_runner']}")
        w, wl = power_w(prof, r["device"].get("backend"))
        free = (r.get("metrics") or {}).get("free_ram_min_mib")
        ram_ok = None if free is None else free >= 2048
        score = lo * pen * (0.5 if ram_ok is False else 1.0)
        cands.append({"score": round(score, 2), "tg_tps": [lo, hi], "evidence": "measured", "contention_factor": round(pen, 2),
                      "contention": why, "backend": r["device"].get("backend"), "device": r["device"]["name"],
                      "model": r["model"], "settings": r["settings"], "free_ram_min_mib": free, "ram_floor_ok": ram_ok,
                      "watts": w, "watts_label": wl, "tokens_per_joule": round(lo * pen / w, 3) if w else None,
                      "source": r["source"], "concurrent_record": bool(c)})
    cands = [c for c in cands if not c["concurrent_record"]] or cands
    # keep best per (backend, model)
    best = {}
    for c in sorted(cands, key=lambda c: -c["score"]):
        best.setdefault((c["backend"], json.dumps(c["model"], sort_keys=True)), c)
    ranked = sorted(best.values(), key=lambda c: -c["score"])
    if not ranked and prof:
        # interpolate from the hardware profile (other hosts with the same hardware)
        for h, pid in host_map().items():
            if pid == host_map().get(host) and h != host:
                ranked = [dict(c, evidence=f"interpolated from {h} (same hardware profile) - FLAGGED")
                          for c in suggest(h, role, recs, graph)]
                break
    return ranked

def node_snippet(host, role, c):
    s = c["settings"]
    return yaml.safe_dump({"nodes": {f"{host}-{role}": {
        "model": "<models key for %s %s>" % (c["model"].get("repo"), c["model"].get("quant")),
        "host": host, "runtime": "<runtimes key>", "role": role,
        "offload": {"backend": c["backend"], "ngl": s.get("ngl", 0), "split": "none", "main_gpu": 0},
        "threads": s.get("threads"), "status": "planned",
        "registry_evidence": f"{c['evidence']}: tg {c['tg_tps'][0]}-{c['tg_tps'][1]} t/s ({c['source']})"}}},
        sort_keys=False)

def match(measure, profs):
    """measure: dict with cpu/os/ram_mib (+ optional gpu, runtime, sku). Returns [(score, id, warnings)]."""
    out = []
    cpu = (measure.get("cpu") or "") + " " + (measure.get("sku") or "") + " " + (measure.get("board") or "")
    for pid, p in profs.items():
        idn = p["identity"]; warn = []
        hits = [k for k in idn.get("cpu_match", []) if k.lower() in cpu.lower()]
        if not hits: continue
        score = len(hits)
        os_ = (measure.get("os") or "").lower()
        if os_ and not idn["os"].lower().startswith(os_.split("-")[0]): warn.append(f"os {os_} != profile {idn['os']}"); score -= 1
        ram = measure.get("ram_mib")
        if ram and abs(ram - idn.get("ram_mib", ram)) > 0.15 * idn["ram_mib"]: warn.append(f"ram {ram} MiB vs profile {idn['ram_mib']}")
        sku = measure.get("sku")
        if sku and idn.get("sku") and sku not in idn["sku"]: warn.append(f"sku {sku} not in tested {idn['sku']}")
        rt = measure.get("runtime")
        if rt and not any(rt in t or t in rt for t in idn.get("runtime_tested", [])):
            warn.append(f"runtime '{rt}' differs from tested {idn['runtime_tested']} - re-measure before trusting t/s")
        gd = measure.get("gpu_driver")
        if gd and idn.get("gpu_driver") and gd not in idn["gpu_driver"]: warn.append(f"gpu driver {gd} vs {idn['gpu_driver']}")
        out.append((score, pid, warn))
    return sorted(out, key=lambda t: -t[0])

def private_leaks(profs):
    bad = []
    hosts = set(host_map())
    for pid, p in profs.items():
        txt = yaml.safe_dump(p)
        if PRIVATE.search(txt): bad.append(f"{pid}: private-looking value ({PRIVATE.search(txt).group(0)})")
        for h in hosts:
            if re.search(r"\b%s\b" % re.escape(h), txt): bad.append(f"{pid}: mentions our hostname {h}")
    return bad

def graph_warnings(graph, recs=None):
    recs = load() if recs is None else recs
    hosts = {r["host"] for r in recs}
    w = []
    for name, n in (graph.get("nodes") or {}).items():
        if n.get("host") not in hosts:
            w.append(f"nodes.{name}: no model-registry evidence for host {n.get('host')} (see docs/model-registry.md)")
            continue
        mk = n.get("model", "")
        stem = re.split(r"[-_]", mk)[0].lower()
        if not any(stem and stem in json.dumps(r["model"]).lower() for r in filt(recs, host=n["host"])):
            w.append(f"nodes.{name}: no registry record for model {mk} on {n['host']}")
    return w

def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: registry.py suggest --host miryam --role coder",
    )
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("add"); a.add_argument("file")
    q = sp.add_parser("query"); q.add_argument("--host"); q.add_argument("--model"); q.add_argument("--backend")
    sp.add_parser("summarize")
    s = sp.add_parser("suggest"); s.add_argument("--host", required=True); s.add_argument("--role", required=True, choices=ROLE_MODELS)
    m = sp.add_parser("match"); m.add_argument("--measure-json"); m.add_argument("--graph"); m.add_argument("--host")
    p = sp.add_parser("power"); p.add_argument("--host")
    sp.add_parser("lint")
    o = ap.parse_args(argv)
    recs = load()
    if o.cmd == "add":
        r = json.load(sys.stdin if o.file == "-" else open(o.file))
        r.setdefault("recorded_at", datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
        append(normalize(r)); print("registry: appended (%d records)" % (len(recs) + 1)); return 0
    if o.cmd == "query":
        for r in filt(recs, o.host, o.model, o.backend): print(json.dumps(r, sort_keys=True))
        return 0
    if o.cmd == "summarize":
        print(f"{len(recs)} records, {len(profiles())} hardware profiles")
        for h in sorted({r['host'] for r in recs}):
            rs = list(filt(recs, host=h))
            print(f"  {h} [{host_map().get(h)}]: {len(rs)} records")
            for r in rs:
                lo, hi = tg(r); c = " (concurrent: %s)" % r["concurrency"]["co_runner"] if r.get("concurrency") else ""
                print(f"    {r['timestamp'][:16]} {r['device']['backend']:<14} {r['model'].get('repo','')[:38]:<38} {r['model'].get('quant',''):<7} tg {lo}-{hi}{c}")
        return 0
    if o.cmd == "suggest":
        ranked = suggest(o.host, o.role, recs)
        if not ranked: print(f"no registry evidence for {o.role} on {o.host}; measure first"); return 1
        for i, c in enumerate(ranked, 1):
            print(f"{i}. {c['backend']} {c['model'].get('repo')} {c['model'].get('quant')}: score {c['score']} "
                  f"(tg {c['tg_tps'][0]}-{c['tg_tps'][1]} t/s {c['evidence']}; contention x{c['contention_factor']}; "
                  f"RAM floor {'ok' if c['ram_floor_ok'] else 'unknown' if c['ram_floor_ok'] is None else 'VIOLATED'}; "
                  f"~{c['watts']} W {c['watts_label']}; ~{c['tokens_per_joule']} tok/J estimate)")
            for wy in c["contention"]: print("     " + wy)
        print("\n# proposed graph.yaml snippet (not written):"); print(node_snippet(o.host, o.role, ranked[0])); return 0
    if o.cmd == "match":
        if o.measure_json: meas = json.load(open(o.measure_json))
        elif o.graph and o.host: meas = yaml.safe_load(open(o.graph))["hosts"][o.host]
        else: ap.error("match needs --measure-json or --graph + --host")
        res = match(meas, profiles())
        if not res: print("no matching hardware profile; please contribute one (docs/model-registry.md)"); return 1
        score, pid, warn = res[0]; prof = profiles()[pid]
        print(f"profile: {pid} (score {score})")
        for w in warn: print("  WARNING: " + w)
        print("known-good setup:"); [print("  - " + x) for x in prof.get("known_good_setup", [])]
        print("gotchas:"); [print("  - " + x) for x in prof.get("gotchas", [])]
        print("# pre-filled defaults (not written):"); print(yaml.safe_dump({"best_settings": prof.get("best_settings")}, sort_keys=False))
        return 0
    if o.cmd == "power":
        for h, pid in host_map().items():
            if o.host and h != o.host: continue
            prof = profiles().get(pid)
            for r in filt(recs, host=h):
                if r.get("concurrency"): continue
                lo, _ = tg(r); w, wl = power_w(prof, r["device"]["backend"])
                if w: print(f"{h} {r['device']['backend']:<14} {r['model'].get('repo','')[:30]:<30} {lo:>7} t/s  ~{w} W  ~{lo/w:.2f} tok/J  [{wl}]")
        return 0
    if o.cmd == "lint":
        bad = private_leaks(profiles())
        for b in bad: print("registry: ERROR: " + b)
        return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
