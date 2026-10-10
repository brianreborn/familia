# gpu-legacy (qodesh GeForce 8600 GT sm_11)

Always-active model path: full forward on GPU (activations + KV in VRAM, logits only copied back).

## Results (stories15M fp32, greedy, Athlon II X2 B24, 2 threads)
| mode | tok/s | notes |
|---|---|---|
| CPU llama2.c | 70.4 | baseline |
| GPU matvec-only (old) | 17-18 | activations bounced each matmul |
| GPU full forward, 48 MiB resident | 19.2 | |
| GPU full forward, 57 MiB all-resident | **21.9** | identical greedy text to CPU |

VRAM free observed 105-114 / 256 MiB (desktop shares the card). stories15M (57 MiB) fits entirely — the always-active decision/draft role.

## Layout
- `kernels.ptx` — matvec, rmsnorm, add, silu_mul, rope, copy, attn_scores, softmax, attn_value
- `sm11_shim.c` — CUDA driver API, on-device forward
- `legacy_gpu.h` — pluggable backend contract (sm11 now; dxcs/ocl11/vulkan later)
- `build-gcc.bat` — WinLibs gcc, no MSVC/CUDA toolkit

## Env
- `FAMILIA_GPU=1` enable
- `SM11_RESIDENT_MIB` cap resident weights
