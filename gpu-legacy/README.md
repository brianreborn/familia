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

## ggml / llama.cpp b11540 (WinLibs gcc, Athlon II, no AVX)
Built `llama-simple` at `E:\temp\llama.cpp\build-sm11\bin`.
Hook: F32 gemv `MUL_MAT` via `SM11_OFFLOAD=1` (ith0 + barrier; stream-only weights).

| mode | eval tok/s | greedy match |
|---|---|---|
| CPU F32 (`SM11_OFFLOAD=0`) | ~58 | — |
| GPU partial F32 offload | **5.8** | **identical** to CPU |
| Q4_0 | CPU only (hook is F32) | — |

Always-active full-forward (llama2.c) remains the winner for a resident decision model (~35 tok/s). ggml path is for **partial offload of a larger active F32 graph** while the CPU owns the rest — slow alone on 8600 GT due to WDDM, valuable for concurrency / other iGPUs later.
