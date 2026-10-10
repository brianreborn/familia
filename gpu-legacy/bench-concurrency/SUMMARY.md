# Concurrency bench - qodesh Athlon II X2 (2 threads), pinned

| run | CPU Q4_0 tg256 (t/s) | GPU stories15M (t/s) | combined |
|---|---:|---:|---:|
| alone | 80.74 | 17.30863 | 98.04863 |
| concurrent (CPU0+CPU1) | 75.24 | 16.306844 | 91.546844 |

Delta CPU: -6.8%
Delta GPU: -5.8%
Net: combined_both=91.546844 vs max(alone)=80.74 vs sum(alone)=98.04863
Pinning: CPU llama-bench affinity=CPU0 (mask 1), GPU run_sm11 affinity=CPU1 (mask 2).
