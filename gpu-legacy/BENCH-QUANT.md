# SM11 quant + batch launch measurements (qodesh, GeForce 8600 GT)

Shape: n=288, d=768 (stories15M FFN-ish). Timing: QueryPerformanceCounter, 100 iters after warmup.
F32 weights registered resident (no per-call W H2D). Q4/Q8 still H2D their packed buffers each call.

## Correctness (max abs err vs CPU F32; y in [-16.7, 18.9])
| op | max_abs_err |
|---|---:|
| gpu F32 | 6e-6 |
| gpu Q4_0 (GGML nibble layout) | 0.491 (~2.6% of peak) |
| gpu Q8_0 | 0.035 |
| gpu batch | 6e-6 |

## Quant matvec latency
| op | ms/call |
|---|---:|
| cpu F32 | 0.346 |
| gpu F32 resident | 0.495 |
| gpu Q4_0 | 3.463 |
| gpu Q8_0 | 3.935 |

## Launch overhead: pipelined batch vs N synced singles
| N | batch ms | N x single ms | speedup |
|---:|---:|---:|---:|
| 3 | 1.236 | 1.530 | 1.24x |
| 6 | 2.237 | 3.037 | 1.36x |
| 8 | 2.959 | 4.115 | 1.39x |

Batch = persistent scratch pool + pipelined `matvec_d` + one `cuCtxSynchronize`.
PTX: `k_q4_matvec`, `k_q8_matvec`, `k_matvec_batch` (pipeline path used on sm_11).
API: `sm11_q4_matmul`, `sm11_q8_matmul`, `sm11_matvec_batch`.
