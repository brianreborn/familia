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
