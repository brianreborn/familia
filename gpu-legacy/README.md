# gpu-legacy — always-active + partial offload on old GPUs

## Best number so far (qodesh 8600 GT, stories15M fp32 greedy)
| mode | tok/s |
|---|---|
| CPU | ~69 |
| GPU full forward + CPU classifier + fused attn | **33–37.5** |
| GPU hybrid partial (SM11_PARTIAL=ffn,wcls) | ~23.5 |

Identical greedy text to CPU. All weights resident (57 MiB / ~113 MiB free VRAM).

## Env
- `FAMILIA_GPU=1` — enable
- `SM11_PARTIAL=ffn,wcls` — CPU forward, GPU selected matvecs (worse alone; for concurrency)
- `SM11_FULL_FWD=1` — force on-device forward even if PARTIAL set
- `SM11_GPU_CLS=1` — vocab matvec on GPU (usually slower)
- `SM11_PTX` — path to kernels.ptx

## ggml-sm11/
Scaffold for llama.cpp MUL_MAT offload. Next: build b11540 with WinLibs gcc and hook F32 mul_mat.

## stories42M (fp32, n=32)
| mode | tok/s | residency |
|---|---|---|
| CPU | 27.7 | — |
| GPU full fwd + CPU cls | 6.1 | 79/159 MiB resident (streams rest) |

GPU loses hard when weights don't fit — confirms always-active role must be << free VRAM (~100 MiB).

## llama.cpp
WinLibs gcc build of b11540 `llama-simple` works on Athlon II (no AVX). SM11 MUL_MAT hook patched into ggml-cpu; rebuild in progress.
