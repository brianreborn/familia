"""Coherent 64K / software-VVRAM policy (docs/vvram-ssd/LAYER.md).

Hermes MINIMUM_CONTEXT_LENGTH is 64000. Hosts that cannot hold weights+KV+cache
in (ram_mib - reserve_ram_mib) must use mmap + spill_path/slot_save + swap_budget_mib
and pass validate_graph --check-swap. Otherwise validate errors / LAUNCH_FAILED
LF_NEED_SPILL — never silent OOM. RAM-fit hosts (miryam Qwen3.5-2B @ 64K) may use
load_mode none. reserve_ram_mib is never lowered to "make room"; spill is SSD.
"""
from __future__ import annotations

import os

# Imported lazily-friendly: validate_graph passes gguf_meta / kv_mib callables.


def vvram_spill_configured(n) -> bool:
    return (
        n.get("load_mode") == "mmap"
        and bool(n.get("spill_path") or n.get("slot_save"))
        and n.get("swap_budget_mib") is not None
    )


def admit_peak_mib(graph, name, *, gguf_meta, kv_mib) -> int:
    """Fleet admission / MemoryMax for one node.

    mmap+swap_budget: charge KV + cache + 1536 MiB working set (not full GGUF).
    Else: historical filesize*1.15+768.
    """
    n = graph["nodes"][name]
    m = graph["models"][n["model"]]
    path = os.path.expanduser(m["gguf"])
    weight = (os.path.getsize(path) / 2**20) if os.path.isfile(path) else 0.0
    if vvram_spill_configured(n):
        try:
            meta = gguf_meta(path) if os.path.isfile(path) else {}
        except Exception:
            meta = {}
        arch = meta.get("general.architecture") or m.get("arch")
        kv = kv_mib(meta, arch, n["ctx"], n["kv_type"]) or 0
        return int(kv + float(n.get("cache_ram_mib") or 0) + 1536)
    return int(weight * 1.15 + 768)


def check_vvram_policy(graph, metas=None, *, gguf_meta, kv_mib):
    """Hard errors when oversize nodes lack the mmap+spill+swap_budget triple."""
    errs = []
    hosts = graph.get("hosts") or {}
    models = graph.get("models") or {}
    for name, n in (graph.get("nodes") or {}).items():
        if n.get("status") == "planned":
            continue
        h = hosts.get(n.get("host")) or {}
        ram = h.get("ram_mib")
        if not isinstance(ram, int):
            continue
        reserve = int(h.get("reserve_ram_mib") or 0)
        m = models.get(n["model"]) or {}
        path = os.path.expanduser(m.get("gguf") or "")
        meta = (metas or {}).get(name)
        if meta is None and path and os.path.isfile(path):
            try:
                meta = gguf_meta(path)
            except Exception:
                meta = {}
        weight = (os.path.getsize(path) / 2**20) if path and os.path.isfile(path) else 0.0
        arch = (meta or {}).get("general.architecture") or m.get("arch")
        kv = kv_mib(meta or {}, arch, n["ctx"], n["kv_type"]) if meta else None
        est = weight + (kv or 0) + 256 + float(n.get("cache_ram_mib") or 0)
        budget = ram - reserve
        if est <= budget:
            continue
        if vvram_spill_configured(n):
            continue
        errs.append(
            f"nodes.{name}: estimated ~{est:.0f} MiB (weights+KV+cache+overhead) exceeds "
            f"host {n.get('host')!r} usable {budget} MiB (ram_mib {ram} - reserve_ram_mib {reserve}). "
            f"Set load_mode: mmap, spill_path (or slot_save), and swap_budget_mib, or reduce ctx; "
            f"refusing silent OOM (docs/vvram-ssd/LAYER.md). Launch would be LAUNCH_FAILED LF_NEED_SPILL."
        )
    return errs
