# SmolLM2-135M-Instruct Q4_0 (GGUF) on the 8600 GT via ggml-sm11

Measured 2026-10-10 PT on qodesh. llama.cpp b11540 + ggml-sm11 hook (`ggml-sm11/llama.cpp-b11540-sm11.patch`),
`SM11_OFFLOAD=1`, `-t 1`, tg128. GPU process pinned to CPU1, CPU coder (stock b11540, same model) pinned to CPU0.

| run | GPU-offload SmolLM2 (t/s) | CPU SmolLM2 (t/s) | combined |
|---|---:|---:|---:|
| alone | 4.49 | 12.03 | - |
| concurrent | 4.52 | 10.59 | 15.11 |

- VRAM: 56 MiB of Q4_0 block weights resident (all 210 matmuls). The tied Q8_0 output/embedding (~30 MiB) stays on CPU
  because the 16 MiB VRAM safety margin (`SM11_VRAM_MARGIN_MIB`) would be violated (free 37 MiB after blocks).
- Kernel: GGML Q4_0, 4 lanes per block, shared x, grid-stride rows (32 CTAs). Max err vs CPU dequant ref 1e-5.
  576x1536 2.2 ms, 1536x576 1.1 ms, 576x576 1.0 ms, 576x192 0.7 ms (bench_smolshape.c).
- Verdict: works and fits, but per-op WDDM sync (~211 matvecs/token) caps it at ~4.5 t/s, slower than one CPU core (12 t/s).
  It is net-additive only as a second, mostly independent stream (combined 15.1 vs 12.0 CPU alone).
  For the always-on decision role, stories15M sm11 full-forward (34 t/s) remains the faster GPU path.
