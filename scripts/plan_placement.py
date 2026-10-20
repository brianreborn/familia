#!/usr/bin/env python3
"""plan_placement.py: predict decode tok/s from measured links and rank placements.

  plan_placement.py LINKS.jsonl MODEL.gguf [--active-frac F] [--measured TG] [--eff E]
Decode is bandwidth bound: tg = eff * host_ram_GBps / bytes_read_per_token, where
bytes_read_per_token = file_size * active_frac (1.0 dense; MoE: active/total params).
A layer offloaded to the GPU instead pays vram + one PCIe hop per token for the activations
(tiny), so the planner only places layers on the GPU when the weights fit in free VRAM.
Layer streaming (#90, AirLLM-style): when the weights do not fit in free VRAM, every layer is
copied host->VRAM once per token into one of two VRAM slots and read there; with a copy engine
and the device read on another stream the two overlap, so a token costs
max(bytes/pcie_h2d, 2*bytes/vram_copy_rw) + launch overhead per layer (gpu-legacy/layer_stream.c
measures it). --ram-budget BYTES below the model size adds disk streaming (mmap re-reads from
disk each token at the measured disk_read rate). --placement picks one mode (default: best).
--measured prints the error vs a measured tg (target: within 30%). Stdlib only."""
import argparse, json, os, sys


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def link(recs, name, how=None):
    xs = [r for r in recs if r.get("link") == name and (how is None or r.get("how") == how) and "GBps" in r]
    return xs[-1]["GBps"] if xs else None


def layer_count(path):
    try:
        import bench_guard
        kv = bench_guard.read_gguf(path)
        arch = kv.get("general.architecture")
        return int(kv.get("%s.block_count" % arch) or 0) or None
    except Exception:
        return None


def predict(recs, model_bytes, active_frac=1.0, eff=1.0, layers=None, ram_budget=None):
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
    h2d = link(recs, "pcie_h2d", "pinned")
    if vram and h2d and per_tok > free * 0.8:
        nl = layers or 32
        # a layer that does not fit twice in VRAM streams in tensor-sized pieces (units)
        import math
        per = max(1, math.ceil(2 * per_tok / nl / (free * 0.8)))  # pieces per layer
        units = nl * per
        unit = per_tok / units
        t = max(per_tok / (h2d * 1e9), 2 * per_tok / (vram * 1e9)) + units * 2 * 10e-6
        out.append({"placement": "layer-stream", "tg_pred": round(1 / t, 3), "layers": nl, "units": units,
                    "unit_MiB": round(unit / 1048576, 2), "vram_MiB": round(2 * unit / 1048576, 1)})
    disk = link(recs, "disk_read")
    if disk and ram_budget and ram_budget < per_tok:
        miss = per_tok - ram_budget  # bytes that fall out of the page cache every token
        t = ram_budget / (eff * ram * 1e9) + miss / (disk * 1e9)
        out.append({"placement": "disk-stream", "tg_pred": round(1 / t, 3), "ram_budget_GB": round(ram_budget / 1e9, 3)})
        out = [r for r in out if r["placement"] in ("disk-stream", "layer-stream")] or out
    return sorted(out, key=lambda x: -x["tg_pred"])


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("links"); a.add_argument("model")
    a.add_argument("--active-frac", type=float, default=1.0)
    a.add_argument("--eff", type=float, default=1.0, help="fraction of memcpy bandwidth decode reaches")
    a.add_argument("--measured", type=float)
    a.add_argument("--layers", type=int, help="layer count (default: GGUF block_count)")
    a.add_argument("--ram-budget", type=float, help="bytes of RAM the model may keep cached")
    a.add_argument("--placement", help="cpu | gpu-legacy | layer-stream | disk-stream (default: best)")
    o = a.parse_args(argv)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    res = predict(load(o.links), os.path.getsize(o.model), o.active_frac, o.eff,
                  o.layers or layer_count(o.model), o.ram_budget)
    if o.placement:
        res = [r for r in res if r["placement"].startswith(o.placement)]
    for i, r in enumerate(res):
        if o.measured and i == 0:  # --measured compares against the selected (first) placement
            r["measured"] = o.measured
            r["err_pct"] = round(100 * (r["tg_pred"] - o.measured) / o.measured, 1)
        print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
