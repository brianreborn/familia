# BENCH — Methodology (one coordinator SSH)

Aligned with thread: isolation crosstalk, zero-copy DMA metrics (when hardware exists), FreeBSD `hwpmc` / `pmcstat`. Until DMA works, use the same coordinator pattern for **software VVRAM** and **gpu-legacy** smokes.

## Coordinator

- One SSH hub host runs the harness (box or miryam).
- Targets: angel (Nanbeige / nvso), qodesh (sm11 — when online, sole Worker), miryam (Vulkan).
- Never co-start two heavy nodes on angel; never parallel qodesh workers.

## Software VVRAM (angel Nanbeige) — runnable once activated

Record per run (JSONL under `~/perf/logs/` or install-notes `perf/`):

| Field | Example |
|-------|---------|
| host / node | angel / angel-coder |
| load_mode | mmap |
| swap_used_mib before/after | from `swapinfo` |
| RSS / VSZ peak | `ps` / `top` |
| pp_t_s / tg_t_s | llama timings or HTTP usage/wall |
| ctx, kv_type, threads | graph facts |
| spill_path hits | if slot_save enabled |
| enable_thinking | false for empty-content Qwen-family; Nanbeige per card |

Protocol:

1. Idle baseline: `swapinfo -k`, `vmstat 1 5`, free RAM.
2. Start **one** node; wait `/health`.
3. Warmup 1 request; then 3 timed generations (fixed seed/temp).
4. Concurrent optional: tiny decision elsewhere — not second Nanbeige.
5. Tear down; capture swap delta + dmesg OOM.

## nvso / soft HVVRAM (angel)

1. `nvsoctl -n` → ABI + ioctl numbers (no device OK).
2. After `kldload`: `nvsoctl` create→map→gate soft round-trip (expect status 0 soft); record ioctl latency_us.
3. Soft `NVGPU_DMA_POST`: desc counts only — not zero-copy proof.
4. When **custom FW** exists ([FIRMWARE-PLAN.md](./FIRMWARE-PLAN.md)): queue export + map; compare bounce vs peer DMA counters.

## Crosstalk / isolation

- Pin coordinator load away from target CPUs when possible (`cpuset` on FreeBSD).
- For G84 SO-domain fantasy: measure interference between domains once hardware exists; today measure angel Nanbeige vs idle desktop only.

## gpu-legacy (qodesh)

Reuse `gpu-legacy/BENCH-*.md` and `docs/perf/qodesh-gpu-legacy/`. Coordinator only queues; Worker executes.

## Box dogfood (already)

`/workspace/familia-install-notes/perf/2026-10-26-box-multi-size.json` — multi-size CPU; Qwen needs `enable_thinking: false` for non-empty `content`. Helper: `scripts/perf/box_multi_size_smoke.py`.
