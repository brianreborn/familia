# Concurrency bench — qodesh Athlon II X2 (fast path)

## Root cause of prior 17.3 t/s
1. **Partial residency**: WDDM free VRAM was ~24 MiB → budget left only **4/57 MiB** resident → host-streaming matvecs.
2. **CPU classifier starved**: GPU process pinned to 1 core with `OMP_NUM_THREADS=1` (vocab-32k classifier is OpenMP).

## Fast path
Full `sm11_forward`, **57/57 MiB** resident, `OMP_NUM_THREADS=2`, GPU process **unpinned**; CPU llama-bench affinity=CPU0 `-t 1`.

| run | CPU Q4_0 tg256 (t/s) | GPU stories15M (t/s) | GPU resident MiB | combined |
|---|---:|---:|---|---:|
| alone | 88.53 | 34.036305 | 57/57 | 122.566305 |
| concurrent | 69.74 | 25.914634 | 57/57 | 95.654634 |

Delta CPU: -21.2%
Delta GPU: -23.9%
