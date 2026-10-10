# SM11 quant matvec — optimized (qodesh, GeForce 8600 GT / G84, 4 SMs)

## Changes vs v1
- Shared-memory cache of `x` (coalesced load, 64 threads)
- 64 threads/block (better occupancy on sm_11)
- Resident quantized W pool (upload once per host pointer)
- Persistent dx/dy scratch (no per-call alloc)

## Measured (QPC, resident W after first call)

| shape (n×d) | cpu F32 ms | gpu F32 ms | gpu Q4 ms | gpu Q8 ms | Q4 vs CPU |
|---|---:|---:|---:|---:|---:|
| 288×768 (stories15M) | 0.312 | 0.403 | **1.072** | 1.518 | 3.44× (was 11× / 3.46 ms) |
| 512×1536 | 1.179 | **0.784** | 2.341 | 2.620 | 1.99× |
| notes | | GPU F32 beats CPU at mid size | | | |

Q4 max-abs-err ~0.49 on y∈[-17,19] (~2.6% peak); Q8 ~0.035.
Target "beat CPU F32" holds for **gpu F32** at ≥512×1536; Q4 still dequant-bound on G84 but **3.2× faster** than prior kernel at stories15M shape.
G84 = 4 SMs confirmed via device path (cc 1.1, 256 MiB).
