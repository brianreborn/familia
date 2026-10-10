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

## 15. Dropping the register prefetch (v3), ptxas -v and occupancy (08:00 UTC)
- `ptxas -arch=sm_11 -v`: k_q4f **37 -> 22 regs/thread**, k_q8f **36 -> 23**, no local-memory spills either way. The 12-word prefetch cost 15 registers, which bought no latency hiding on sm_11.
- Occupancy from cuFuncGetAttribute: k_q4f with 576-wide x (64 thr, 5.3 KB smem) runs 3 CTAs/SM. Shared memory (x cache + weight chunk), not registers, is now the limit at every tuned config (1536-wide: 1 CTA/SM at 13.9 KB). k_attn_mh and k_rope_kv reach 100%.
- Re-sweep with grids down to 4: the best configs are **1 CTA per SM** (G=4, R=32, 256 threads) for the 576-wide matvecs. Fewer, wider CTAs win because each CTA re-does the x prologue (load + rmsnorm) and its barriers.
- Kernel GB/s, v2 -> v3: 576x3072 **0.74 -> 0.88**, 576x960 0.69 -> 0.76, 1536x576 0.75 -> 0.77, Q8 classifier 576x49152 **1.06 -> 1.29**.
- End to end, same session: SmolLM2 **7.84-7.89 tok/s (v2) -> 9.53-9.78 (v3)**, about +24%. 32/32 vs the CPU ref on all 4 prompts. Serve inflight 1/2 runs at 9.77/9.79 tok/s with identical outputs.
- Desktop was idle this session: stories15M 70.2-71.2 (blocking) vs 69.6-70.2 (async), identical text. The coder ran 116.9 alone, 114.0 with the decision server, 113.8 with stories15M (37.2 tok/s).
- Still about 1 GB/s against 22 GB/s peak. The next levers are the shared-memory footprint (stream the weight chunk in halves so 2-3 CTAs/SM fit) and computing the norm once per token instead of once per CTA.

## 16. Half-size weight chunks vs rmsnorm once per token (08:02-08:12 UTC, 112-120 MiB free)
- **Loading the weight chunk in halves loses.** Halving the chunk (R/2 rows, 2L lanes, same 256 threads) cuts dyn smem from 13.8 KB to about 7 KB, so 2-4 CTAs fit per SM. That's 33% -> 67-100% of the thread slots on paper. But end to end it runs **8.39-8.79 tok/s vs 9.86-9.93** (prenorm) and **8.46-8.50 vs 9.71-9.78** (fused norm). In the kernel sweep the small-chunk configs also lose (576x960 at R=4/L=16/G=16 with 4 CTA/SM: 0.423 ms, vs 0.379 ms at 1 CTA/SM). Each CTA redoes the x prologue and its barriers, and bigger chunks mean fewer global staging rounds, so on G84 occupancy isn't what limits us.
- **rmsnorm once per token** (one small k_rmsnorm into a normed-x buffer, then the matvec without the norm prologue): kernel 576x3072 **0.87 -> 0.91 GB/s**, 576x960 0.74 -> 0.82, Q8 classifier 0.99 -> 1.06. End to end **9.71-9.78 -> 9.86-9.93 tok/s** (+1.5%) on all 4 prompts, 32/32 vs the CPU ref. That's despite 3 extra launches per layer: the launch costs about 0.02 ms and the per-CTA reduction it removes cost more. Now the default (`SMOL_PRENORM=0` switches back).
- PowerShell trap again: `foreach($p in $P)` overwrote `$P` (variable names are case-insensitive), so the first comparison silently ran only 1 prompt for later configs. Rerun with distinct names.
- Still about 1 GB/s. Since occupancy isn't the limit, the remaining cost is per-weight ALU and shared-memory bank traffic (u16 nibble loads, 4 x-loads per 4 weights). Next lever: register-block 2 rows per thread to share the x loads, or pre-quantize x to int and use mad24.
- Serve, prenorm default, 4 req x 32 tok: serve inflight=2 requests=4 forward_tokens=163 wall=16.41s -> 9.93 tok/s (gen 32/req), host polls 7872, gpu blocking waits 123, idle spins 2324, idle blocks 1

## 2026-10-10 wait loops that do useful work instead of pure polling (SmolLM2 decision node)
- What it does: SMOL_WAIT=1 (now the default) means that while token N's event is pending, the host does bounded chunks of work (each ~10-50 us or less). Single-sequence: it pre-embeds the next *known* prompt token into a per-sequence double-buffered pinned buffer. That's safe because the free buffer belongs to token N-1, whose H2D copy is already complete. Serve worker: it pre-embeds the next prompt token for every in-flight request, and it drains and prefetches the next ring request into a staging slot. Stats sit on their own 64 B line. When there's nothing left, it spins 64x YieldProcessor and then blocks on the event (BLOCKING_SYNC context).
- A/B over 2 reps x 2 prompts x 32 tokens, plus serve inflight=2. Every run matched 32/32 vs the CPU:

| wait mode | gpu tok/s | enqueue->ready latency avg/max (ms) | serve tok/s | concurrent gpu tok/s |
|---|---|---|---|---|
| 0 spin64+block (old) | 7.61-7.85 | 126.3-126.9 / 135-153 | 7.86 | 7.65 |
| 1 work+spin+block (new) | 7.85 | 126.3 / 128 | 7.86-7.87 | 7.64-7.65 |
| 2 pure spin (latency floor) | 7.66-7.86 | 126.2-129.0 / 128-154 | 7.83-7.88 | 7.64 |

- Finding: there is almost nothing to overlap. Generation is strictly serial (token N+1 needs N's argmax), and the only host prep is a 576-float embedding (a few us). In 32-token runs that came to 1-2 work chunks for a single sequence and 9 for serve. Blocking-sync wake-up costs <0.1-0.3 ms against a ~126 ms token (pure spin vs block are within the spread). So mode 1 is kept because it is free and removes polling of an idle ring, but it is not a speedup. The big lever stays GPU kernel time.
- Caveat: these A/B runs happened while another app had taken VRAM (free fell to 14 MiB right after). The absolute tok/s (7.8) is under the 12.9 measured with the texture kernel at 123 MiB free, so treat them as relative only. The coder t/s parse failed in this job (llama-bench prints the plus-minus sign, which the ANSI-encoded script mangled); rerun pending.

## 2026-10-10 false-sharing audit
- SPSC rings: head and tail used to share one line with the slot array, and g_in/g_out/stop/ready/stats were packed together in .bss. Now (FS_PAD=1, default): the producer line holds head plus a cached copy of tail; the consumer line holds tail plus a cached copy of head; slots get their own lines plus a trailing pad; stop/ready flags, worker stats, host stats and g_polls each get their own 64 B line.
- Measured on serve, 3 reps x inflight {1,2}: nopad 10.08-10.22 tok/s, pad 10.20-10.23 tok/s. That's within the run-to-run spread (about 0.15). The ring is touched about 10 times per 100 ms token, so there was no measurable contention to remove on a 2-thread Athlon. Kept as hygiene.
- GPU v4 multi-row kernel: x reads at stride 2 words (2-way bank conflict), reduction scratch [t][m] (MR-way), and output written by lane-0 threads spaced L apart (uncoalesced). v5 fixes all three: planar x P_j[b*8+k], padded [m][rg*(L+1)+lane] scratch, and consecutive threads writing consecutive rows. End-to-end it is *slower* with the v4 configs: MR2 tex 10.2 vs 12.9 tok/s, MR4 tex 11.9. The extra index math in the x prologue and in the reader setup costs more than the conflicts it removes, since the kernel is ALU-bound. v5 still needs its own config sweep before it's dropped. v4 stays the default (SMOL_V5=0 is recommended; the code default flips after the sweep).

## 2026-10-10 v4 register-blocked texture kernels (end-to-end, 32/32 vs CPU on 3 prompts)
| kernel | tok/s |
|---|---|
| v3 fused (old default) | 9.94-10.40 |
| v4 MR1 tex | 11.10 |
| v4 MR2 tex | 12.86-12.91 |
| v4 MR4 tex | 10.17-10.25 |
| v4 MR2 global loads (no tex) | 7.85 |

- The texture cache is what makes this design work (1.6-1.8x over plain ld.global). MR=2 is the register/ILP sweet spot.

## Repetition counts (reduced per user directive)
- Correctness: 2 prompts x 32 tokens, full token match. The 3rd prompt never disagreed with the other two in any run this session.
- tok/s A/B: 2 reps. Spread is about 0.05-0.2 tok/s (about 1-2%). Stop cutting when an effect gets under about 2x that.
- kbench sweeps: 50 iterations per config (each config's spread is <3%). Coder llama-bench: -n 64 -r 2.

### Wait-mode rerun with 139 MiB VRAM free (1 rep; spread from the earlier 2-rep run is about 0.05 tok/s)
| mode | gpu tok/s | latency avg/max ms | serve tok/s | coder t/s (CPU0) concurrent | gpu tok/s concurrent |
|---|---|---|---|---|---|
| 0 old | 12.68-12.88 | 76.6-78.3 / 78-102 | 12.89 | 121.0 | 12.34 |
| 1 work | 12.86-12.89 | 76.5-76.6 / 78 | 12.91 | 124.6 | 12.35 |
| 2 spin | 12.83-12.88 | 76.6-76.7 / 78-81 | 12.96 | 122.0 | 12.32 |
- The coder measured alone *first* came out at 79.2 t/s, below every concurrent run. That looks like a cold-start or clock artifact of running first, so it isn't valid as a baseline yet; next round, run "alone" after a warm-up. Mode 1 has the lowest max latency and no coder penalty. Its differences from the other modes are within spread except the max-latency tail.

## 2026-10-10 rows-per-thread (MR) drop-off sweep, texture Q4 kernel (v6 = v5 layout, MR 1-8, tail rows via texture clamp plus guarded store)
Sweep: RG {2,4,8,16} x BG {1,2,3,6} x G {8,16,32}, 20 iterations per config. Registers and spills come from cuFuncGetAttribute (lmem = local/spill bytes). Occupancy is for the best config.

| MR | regs/thr | spill | CTA/SM @64thr | 576x3072 ms (GB/s) | 1536x576 | 576x960 | 576x576 |
|---|---|---|---|---|---|---|---|
| 1 | 24 | 0 | 5 (42%) | 0.881 (1.13) | 0.444 (1.12) | 0.307 (1.01) | 0.196 (0.95) |
| 2 | 25 | 0 | 4 (33%) | 0.694 (1.44) | 0.395 (1.26) | 0.255 (1.22) | 0.175 (1.07) |
| 3 | 30 | 0 | 4 (33%) | 0.611 (1.63) | **0.331 (1.51)** | 0.227 (1.37) | 0.154 (1.21) |
| 4 | 32 | 0 | 4 (33%) | **0.583 (1.71)** | 0.400 (1.24) | 0.218 (1.43) | **0.153 (1.22)** |
| 5 | 32 | 0 | 4 (33%) | 0.590 (1.69) | 0.349 (1.42) | **0.214 (1.45)** | 0.159 (1.17) |
| 6 | 37 | 0 | 3 (25%) | 0.631 (1.58) | 0.363 (1.37) | 0.242 (1.28) | 0.159 (1.17) |
| 8 | 39 | 0 | 3 (25%) | 0.612 (1.63) | 0.380 (1.31) | 0.241 (1.29) | 0.173 (1.08) |

- Drop-off: gains flatten at MR 3-5 and turn down from MR=6. No configuration spills. The cause is registers then occupancy: going from 32 to 37+ regs/thread drops resident CTAs per SM from 4 to 3, and an ALU-bound kernel with texture latency needs those warps. Odd MR helps the 1536-wide shape (MR=3: 18 rows/CTA-iteration keeps BG=2 at 128 threads). The best sizes per shape differ (4/3/5/4).
- **But end-to-end (2 prompts x 32 tokens, all 32/32) the isolated winners lose:**

| config (Q8 classifier on texture, MR4, in all but base) | tok/s | token latency ms |
|---|---|---|
| base: v4 MR2 Q4 + old Q8 classifier | 12.88 | 76.5 |
| **v4 MR2 Q4 + Q8 classifier tex MR4 (new default)** | **14.58** | 67.5 |
| v6 per-shape MR (4,3,5,4) | 13.99-14.03 | 70.3 |
| v6 all MR4 | 13.51 | 72.9 |
| v6 all MR3 | 13.45 | 73.3 |

  The microbench reruns one matrix 20x, so it measures a warm texture cache. In the real token every matrix is cold and different. The v6 configs (64-thread CTAs, BG=2) appear to depend on that reuse (likely texture-cache thrash or a different access stride once cold), while v4 MR2 (BG=1, RG=8) streams better cold. Lesson: tune with an in-pipeline (cold) benchmark, not a hot loop. Next: rotate across all 30 layers' matrices inside kbench.
- **Q8 classifier on the texture cache** (576x49152, 2 lanes/u16 misaligned-word funnel, MR4, RG8 BG1 G64): 13.8 ms vs 29.9 ms (v3 fused), 2.18 vs 1.01 GB/s, which is about +13% tok/s end to end. The biggest win this round.
- Warm coder-alone baseline (llama-bench stories15M Q4_0, 1 thread, CPU0, after a warm-up run): 123.0-123.9 t/s at tg64. bench_async tg128: alone 115.5 +/- 3.1, alongside the SmolLM2 server 114.3 +/- 1.7 (-1%, inside the spread), alongside stories15M 115.4.
- bench_async full (ran with v6 on by default by mistake, 13.8-14.0 tok/s): stories15M 69.6-71.5 tok/s, text identical; SmolLM2 4 prompts 32/32 vs CPU; serve inflight 1 and 2 at 13.96/13.97 tok/s, outputs identical to single runs.

## 2026-10-10 rotating cold-cache benchmark and per-shape re-tune
- kbench (SMOL_KB_X) now cycles through all 30 layers' matrices: 60 calls per config, each call on a different weight matrix, like a real token. The warm 20x-same-matrix loop overstated the v6 configs.
- Cold results (ms; best config shown as MR / RG,BG,G):

| shape | v4 MR2 (old default) | v4 MR4 | v6 best cold | warm v6 best (previous round) |
|---|---|---|---|---|
| 576x3072 | 0.846 | 0.818 | **0.734** (MR5 8,2,8) | 0.583 |
| 1536x576 | 0.466 | 0.550 | **0.379** (MR3 8,2,8) | 0.331 |
| 576x960 | 0.305 | 0.293 | **0.255** (MR5 4,2,16) | 0.214 |
| 576x576 | 0.166 | 0.215 | **0.142** (MR3 8,2,8) | 0.153 |

  Cold costs 10-25% more than warm, and the ranking changes: MR4 wins warm but loses cold on 3 of 4 shapes. Cold drop-off: MR 3-5 best, and MR 6/8 are again worse on 3 of 4 shapes.
- End to end (2 prompts x 32 tokens, 32/32): v4 MR2 14.46-14.62 tok/s, **v6 cold-tuned 14.80-14.83 (new default, SMOL_X=1)**. That's +1.5% (spread about 0.1). The per-layer kernel sum predicts about 8 ms/token less (1.78 to 1.51 ms per layer x 30), but only about 1 ms showed up. So even the rotating bench isn't the real pipeline: it repeats one shape back-to-back, which lets consecutive launches overlap, and it reuses the same x. Next: a bench that replays the real per-layer launch sequence.
- Q4 classifier fallback on the GPU (used when the Q8 table doesn't fit; requantized Q4 plus CPU top-K Q8 rescoring), 576x49152: v4 MR2 13.2 ms, v4 MR4 12.4, v6 MR4 11.1, **v6 MR5 (4,2,16) 10.4 ms (1.53 GB/s)**, now its default. End to end: 13.99-14.01 to 14.20-14.21 tok/s, 32/32. The CPU-only classifier fallback stays on the CPU (there's no GPU table to read).
- Known stats bug: tok_lat is garbage on the q4-classifier path (the enqueue timestamp isn't set on that path). tok/s and the match check are unaffected.

## 2026-10-10 replay benchmark (real per-layer launch order) and final defaults
- SMOL_KB_REPLAY times whole real token forwards (enqueue_gpu, 6 tokens per setting) and does coordinate descent per shape over MR {2..6} x RG {4,8,16} x BG {1,2} x G {8,16,32}, 2 passes. Invalid settings are rejected with a dry-run check first: register budget regs*T <= 8192, otherwise CUDA 701.
- The replay picks **256-thread CTAs (RG=16, BG=2) with 5 rows/thread** for all four layer shapes. Neither the warm bench nor the rotating cold bench chose that. In the real sequence, big CTAs win: fewer CTAs per launch, and the next launch's CTAs start sooner on a 4-SM G84. Replay: 70.1 to 58.4 ms/token (q8 classifier). Q4-classifier path: shape 4 = MR3 RG8 BG2 G8.
- End to end (32/32 on all runs): cold-tuned 14.57-14.68 tok/s; **replay-tuned 15.31-16.87** (defaults now); Q4-classifier path 14.09 to 16.27-16.28. Verify run of the new defaults: 15.61 / 16.27 tok/s. Spread is wider this session (some runs were 1-1.5 tok/s low; desktop activity on qodesh while the user was on it).
- Lesson: tune with the real sequence. A hot loop over one matrix, or even a rotating loop over one shape, ranks configs differently from the real token.
- Latency bug fixed: the q4-classifier path now sets the enqueue timestamp (tok_lat 60.3 ms instead of garbage).

## Tuning arc (SmolLM2-135M Q4_0 decision node, GeForce 8600 GT sm_11, all 32/32 vs CPU)
| step | tok/s |
|---|---|
| ~211 GPU calls per token, each with a driver sync | ~4.5 |
| full forward on GPU, one sync per token, async plus SPSC rings | ~7.9 |
| fusion without register prefetch | 9.8 |
| norm once per token | 9.9 |
| v4 register-blocked Q4 through the texture cache, 2 rows/thread | 12.9 |
| Q8 classifier through the texture cache, 4 rows/thread (29.9 to 13.8 ms) | 14.6 |
| per-shape rows tuned on the rotating cold bench | 14.8 |
| **per-shape tuned on the real-sequence replay (256-thread CTAs, 5 rows/thread)** | **15.3-16.9** |
