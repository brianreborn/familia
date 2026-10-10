# Decision node concurrency — GPU stories15M + CPU SmolLM2-135M Q4_0

Catalog (#24): K2-Horizon-0.9B Q4_0 ~605 MiB — too large for 256 MiB VRAM.
SmolLM2-135M-Instruct Q4_0 = 87.4 MiB fits the ~100 MiB VRAM budget (GGUF path pending ggml-sm11 Q4 wire-up).
GPU always-on decision node measured here: stories15M FP32 sm11 full-forward (57 MiB resident).
CPU coder-class load: SmolLM2-135M Q4_0 via llama.cpp b11540 `-t 1`.

| run | CPU SmolLM2 Q4 tg128 (t/s) | GPU stories15M decision (t/s) | resident | combined |
|---|---:|---:|---|---:|
| alone | 11.95 | 34.312921 | 57/57 | 46.262921 |
| concurrent | 11.47 | 33.328018 | 57/57 | 44.798018 |

Delta CPU: -4%
Delta GPU: -2.9%
