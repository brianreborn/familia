# PGO follow-up: intermediary tuning results as profile hints

The 2026-10-10 sweeps are profile-guided optimization: measured profiles pick the defaults, and they also show where the next round should look. Ship bar: ~2010-class hardware (qodesh: Athlon II X2 B24, x86-64-v1, no AVX, GeForce 8600 GT 256 MiB).

## Where the data lives
- `registry/records.jsonl`: qodesh, miryam and phone records, plus the pentest launch-test record
- `docs/perf/qodesh-gpu-legacy/`: lessons, sync audit, quant/batch bench, progress log and concurrency summaries (copied from `E:\temp\gpu-legacy` on qodesh; source and kernels stay there)
- `docs/perf/phone8-2026-10-10*.log`: phone Vulkan runs (phones are out of range for now)

## What the measurements suggest
- **qodesh 8600 GT, SmolLM2-135M Q4_0 full forward:** tok/s went 4.5 -> 7.9 -> 9.8 -> 12.9 -> 14.6 -> 15.3-16.9 (replay-tuned: 256-thread CTAs, 5 rows/thread). It has plateaued at ~15-17 tok/s, 32/32 vs CPU. Tuner noise (+/-2 ms per ~61 ms token) is now larger than what the remaining knobs could gain. Attention+RoPE is <1% of the token, so don't fuse QKV+RoPE.
  - Next: tune on the real launch sequence only; use >=32 tokens per setting; record free VRAM (56-139 MiB, shared with the desktop; it decides Q8 vs Q4 classifier); verify zero-copy mapped memory on G84; cut the launch count (~600 per token) with fewer, bigger per-layer kernels.
- **qodesh CPU, non-AVX b11540:** with the GPU node serving, best is coder `-t 1` pinned to CPU0 plus the GPU node on CPU1, about 13.4 + 16.6 = 30 tok/s. `-t 2` strict-pinned collapses (0.28 tg). With the GPU idle, `-t 2` gives 24.6 tg. **Applied:** `cpu-smol-decision threads: 1`. Poll 0, KV q8_0+fa and ubatch don't help at 135M; re-check them on a real coder model.
- **miryam i5-7200U:** decode runs on the CPU, not the iGPU (SmolLM2 CPU 101-110 tg vs Vulkan 46-50). n-gram speculation on edits gives 2.2x with 100% acceptance (Qwen3.5-2B 17.4 tg). The RAM-safety incident hit 212 MiB free, so keep earlyoom+zram and memcap on.

## Next rounds (old-device first)
1. Low-RAM profile for 4-8 GiB / x86-64-v1: ctx 2048, KV q8_0 only with -fa, cache_ram_mib <= 256, threads = cores minus the GPU feeder.
2. Re-run the coder matrix on a real coder model on qodesh.
3. Per-layer kernel merge on sm_11, re-measured at >=32 tokens per setting.
4. Smoke-test the installers' pre-v2 numpy path and non-AVX build on Windows and Linux.
