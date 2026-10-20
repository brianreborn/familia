#!/usr/bin/env python3
"""plan_placement.py: predict decode tok/s from measured links and rank placements.

  plan_placement.py LINKS.jsonl MODEL.gguf [--active-frac F] [--measured TG] [--eff E]
Decode is bandwidth bound: tg = eff * host_ram_GBps / bytes_read_per_token, where
bytes_read_per_token = file_size * active_frac (1.0 dense; MoE: active/total params).
A layer offloaded to the GPU instead pays vram + one PCIe hop per token for the activations
(tiny), so the planner only places layers on the GPU when the weights fit in free VRAM.
--measured prints the error vs a measured tg (target: within 30%). Stdlib only."""
import argparse, json, os, sys


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def link(recs, name, how=None):
    xs = [r for r in recs if r.get("link") == name and (how is None or r.get("how") == how) and "GBps" in r]
    return xs[-1]["GBps"] if xs else None


def predict(recs, model_bytes, active_frac=1.0, eff=1.0):
    # Decode streams weights (reads only). A memcpy moves n read + n written in the time it takes,
    # so the read-stream rate is ~GBps_rw (iteration 2: GBps alone under-predicted by 35%).
    ram = [r for r in recs if r.get("link") == "host_ram"][-1]["GBps_rw"]
    per_tok = model_bytes * active_frac
    cpu = eff * ram * 1e9 / per_tok
    out = [{"placement": "cpu", "tg_pred": round(cpu, 2), "per_token_GB": round(per_tok / 1e9, 3)}]
    vram = link(recs, "vram_copy")
    free = max([r.get("vram_free", 0) for r in recs] or [0])
    if vram:
        frac = min(1.0, free * 0.8 / per_tok) if per_tok else 0
        t = (1 - frac) * per_tok / (eff * ram * 1e9) + frac * per_tok / (eff * vram * 1e9) + 2 * 10e-6
        out.append({"placement": "gpu-legacy %.1f%% of weights (sm11 path only)" % (100 * frac), "tg_pred": round(1 / t, 2)})
    return sorted(out, key=lambda x: -x["tg_pred"])


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("links"); a.add_argument("model")
    a.add_argument("--active-frac", type=float, default=1.0)
    a.add_argument("--eff", type=float, default=1.0, help="fraction of memcpy bandwidth decode reaches")
    a.add_argument("--measured", type=float)
    o = a.parse_args(argv)
    res = predict(load(o.links), os.path.getsize(o.model), o.active_frac, o.eff)
    for r in res:
        if o.measured and r["placement"] == "cpu":  # measured runs are CPU llama.cpp
            r["measured"] = o.measured
            r["err_pct"] = round(100 * (r["tg_pred"] - o.measured) / o.measured, 1)
        print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
