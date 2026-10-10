# Lessons learned: qodesh legacy GPU (GeForce 8600 GT, sm_11, WDDM, Athlon II X2)

Each entry gives the finding, the numbers behind it, and what we do now. Times are PT.

## 1. Per-op host syncs on the Windows (WDDM) driver
- The per-op ggml hook syncs on every op. SmolLM2-135M Q4_0 makes about 211 GPU calls per token, each with a blocking D2H, and runs at **4.5 tok/s**.
- Enqueuing the whole forward pass on the device (`smol_sm11`, about 600 async launches and **1 wait per token**) runs at **8.6–9.0 tok/s** with the same weights. That's 2x from removing the syncs and the hook.
- An async launch costs about **0.008–0.019 ms** to enqueue (k_add / k_rmsnorm, 200 back-to-back with one sync). A per-op sync round trip costs ≥0.1–0.3 ms. On WDDM the sync is the cost, not the launch.
- Swapping that single per-token wait from blocking `cuMemcpyDtoH` to event polling on pinned memory: SmolLM2 **8.67 → 8.62 tok/s**, output identical. That's noise. Once there's only one wait per token, the kind of wait no longer matters. What matters is how many there are.
- Rule: no host sync per op. Sync at most once per token, poll an event, no mutexes. See SYNC-AUDIT.md.

## 2. Residency budget (VRAM margin 16 MiB)
- stories15M with only 4 of 57 MiB resident (staging budget bug) ran at **17.3 tok/s**. Fully resident it runs at **34 tok/s**.
- 210 separate `cuMemAlloc`s for SmolLM2 cost about 8 MiB of overhead (62 MiB resident left 28 MiB free, not about 36). A single arena fixes that, and it's what lets the classifier fit on the GPU.
- Free VRAM on this desktop swings between **72 and 103 MiB** depending on Discord and Firefox hardware acceleration. SmolLM2 needs about 60 MiB + 16 MiB margin. With 72 MiB free the harness refuses to load rather than eat into the margin. The guard is there on purpose.

## 3. OMP / pinning
- When the GPU runner was pinned to one core with OMP_NUM_THREADS=1, stories15M dropped to **17.3 tok/s** (the CPU classifier was starved). Unpinned with OMP=2 it gets **34 tok/s**.
- With the CPU coder pinned to CPU0 (llama-bench stories15M Q4_0, 1 thread) and the GPU runner pinned to CPU1: coder **99.2 tok/s alone → 93.9 tok/s** alongside stories15M async (24.3 tok/s). The coder keeps 95%.

## 4. Q4 dequant cost on sm_11
- cc1.1 only coalesces aligned 64-byte half-warp segments, so reading Q4_0 blocks (18 B stride) straight from global memory is uncoalesced. Fix: stage the contiguous row chunk into shared memory with aligned u32 loads (`k_q4r` / `k_q8r`).
- Shared-memory bank conflicts came next: lanes striding by whole blocks hit the same bank (16-way). Fix: 8 lanes per block, each reading a u16 (4 nibbles) and contiguous x.
- Results (ms per call): 576x1536 **0.745 → 0.49**, 1536x576 **1.62 → 0.59**, 576x576 **0.31 → 0.20**. That's still only about 1 GB/s against a 22 GB/s peak. The kernels are now ALU-bound at about 6 instructions per weight (nibble extraction, cvt, ld x, mad) on 32 SPs.
- A Q8_0 classifier (30 MiB) doesn't fit next to the layers within the margin. On the CPU it costs **43 ms/token**, about 30% of a core. Requantizing it to Q4_0 (16 MiB) on the GPU takes **15.8 ms**, but the greedy output diverges (1/32 tokens match). Rescoring the GPU's top 64 exactly against Q8_0 on the CPU (0.4 ms) brings it back to **32/32**.

## 5. Correctness
- GPU full-forward vs the CPU reference forward (same math, fp32): **32/32 greedy tokens identical on all 4 prompts** (capital-of-France, fibonacci, sentiment, yes/no). Tested both with the classifier as GPU Q8_0 and with Q4 top-64 + exact Q8 rescoring.
- Blocking-sync binary vs async binary: identical token ids (48 tokens). stories15M stdout is identical before and after the async change (checked by hand; the script's automated text compare was buggy).
- vs llama.cpp `llama-simple` (CPU): identical on "The capital of France is". "def fibonacci(n):" diverges after about 12 tokens ("n must" vs "Input must"). The CPU reference agrees with the GPU, so the difference is llama.cpp's Q8_0 activation quantization in its Q4_0 dot products, not a GPU bug.

## 6. Lock-free handoff (SPSC rings + event polling)
- Decision server with 4 requests x 32 generated tokens (163 forward tokens): inflight=1 **8.22 tok/s**, inflight=2 (double-buffered) **8.27 tok/s**. Outputs are byte-identical to the single runs in both modes.
- Double-buffering gains almost nothing because host work per token is now tiny (embedding + argmax; Q8 classifier on GPU). The GPU is the bottleneck at about 120 ms/token. It would pay off if the classifier ran on the CPU (43 ms/token to hide).
- Pinned + event polling vs blocking D2H, both with 1 wait/token: SmolLM2 8.05 → 8.09 tok/s. stories15M best of 3: 31.0 → 33.9 tok/s, within run-to-run noise (28–34).
- Polling costs: the worker does about 200k `SwitchToThread` polls/s on its own core. With the coder pinned to the other core that costs nothing measurable (see 7).

## 7. Concurrency with the CPU coder (llama-bench stories15M Q4_0, 1 thread, pinned CPU0; GPU worker pinned CPU1)
| config | coder tg128 t/s | GPU node t/s |
|---|---|---|
| coder alone | 114.3 | — |
| + SmolLM2 decision server (inflight 2, GPU Q8 cls) | 116.3 | 8.26 |
| + stories15M async full-forward | 110.3 | 26.8 |

## 8. VRAM is shared with the desktop
- Free VRAM before load ranged from **72 to 154 MiB** over 20 minutes as Discord and Firefox (hardware acceleration) grew and shrank. With 150 MiB free the Q8_0 classifier fits (88 MiB resident, 58–61 MiB still free). At 99 MiB the harness falls back to Q4 + rescoring. At 72 MiB it refuses to load to protect the 16 MiB margin.

## 9. Zero-copy mapped memory on WDDM (test_mapped.c)
- G84 reports `CAN_MAP_HOST_MEMORY=1`. A context with MAP_HOST, `cuMemHostAlloc(DEVICEMAP)` and `cuMemHostGetDevicePointer` all succeed, and a kernel writing into mapped memory gives the correct result once synced (3.0 = 1+2).
- But spinning on a host flag in mapped memory **never sees the write** (timed out at 200 ms). WDDM queues the launch in a user-mode command buffer and doesn't submit it to the GPU until something flushes it (an event query or sync). A pure mapped-flag handoff would deadlock on this driver.
- An event fence round trip for a tiny kernel is **0.072 ms**. Rule: on WDDM use events (`cuEventQuery` also flushes) as the completion signal. Mapped memory could carry the payload, but it still needs an event to flush.

## 10. Waiting strategy (spin, then block)
- The context is now created with `CU_CTX_SCHED_BLOCKING_SYNC` (override with `SM11_CTX_FLAGS`). `sm11_fence` and `seq_wait` spin about 64 `cuEventQuery`s, then call `cuEventSynchronize`, which sleeps in the driver instead of burning a core.
- The idle decision-server worker spins 2000 `YieldProcessor` iterations, then blocks on a Win32 auto-reset event that the producer signals after each ring push. Before this it made about 200k `SwitchToThread` polls/s while idle.
- Numbers pending: VRAM was unavailable (entry 11).

## 11. VRAM availability blocks GPU runs
- From 06:59 to 07:12 UTC, free VRAM dropped to **8–17 MiB**, with Firefox and Discord holding the rest. SmolLM2 needs about 60 MiB + 16 MiB margin and stories15M about 57 MiB, so every GPU run correctly refused to load. The margin guard did its job, but on a shared desktop GPU you can't schedule a decision node without coordinating with the desktop apps (turn off hardware acceleration, or reserve VRAM at boot before they start).

## 12. Kernel fusion round (measured 07:40-07:51 UTC, 102-106 MiB VRAM free)
- 6 launches/layer instead of about 22 (about 181 per token instead of about 600): rmsnorm fused into the QKV and gate|up matvecs, silu(g)*u fused into the down matvec's x load, residual add in the epilogue, k_rope_kv, k_attn_mh.
- End to end: SmolLM2 **8.06-8.25 tok/s unfused -> 8.33-8.80 fused** (about +6%), **32/32 vs CPU ref on all 4 prompts**, serve-mode outputs identical to single runs.
- Per byte, though, the v2 kernel (xsum trick, 2 accumulators, 12-word register prefetch) is **slower**: fused 576x3072 takes 1.34 ms vs 2 x 0.49 ms for v1, and 1536x576 takes 0.66 vs 0.59 ms (about 0.7 GB/s vs 1.0). The prefetch costs 12 extra registers per thread (up to 72), which on sm_11 (8192 regs/SM) cuts occupancy more than the hidden latency is worth. The gain comes from fewer launches, not faster math. Next: drop the prefetch and keep the fusion.
- The sweep is still optimal at small grids (G=8, R=8). More CTAs is slower.

## 13. Spin-then-block waits
- Host polls for the 4-request serve run: **4.1M -> 10.4k** (inflight 1) and **2.3M -> 7.9k** (inflight 2), with no change in tok/s (8.52-8.58). The worker no longer burns a core while it waits.
- Coder alongside (CPU0): 90.8 alone / 102.4 with the decision server / 95.5 with stories15M (desktop load varies �10%).

## 14. Bench harness bugs (fixed)
- stories15M text compare: PowerShell turns native stderr into ErrorRecords, which the old filter didn't remove. It now compares stdout strings only, and before vs after is identical.
- `$m` vs `$M`: PowerShell variable names are case-insensitive, so the match variable overwrote the model path.
- In a fresh shell run_sm11 failed with 0xC0000135 (libgomp not on PATH). The script now prepends the mingw bin directory.
- stories15M with the desktop idle: before **57.5-58.4**, after (async + blocking-sync context) **53.3-59.3 tok/s**, identical text.
