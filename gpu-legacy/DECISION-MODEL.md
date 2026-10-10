# Decision catalog pick (#24) for qodesh 8600 GT

| candidate | Q4 size | Fits ~100 MiB VRAM? |
|---|---:|---|
| K2-Horizon-0.9B | ~605 MiB | **no** |
| SmolLM2-135M-Instruct Q4_0 | **87.4 MiB** | **yes** |
| stories15M FP32 (llama2.c / sm11) | 57 MiB | yes (current GPU path) |

SmolLM2 GGUF needs ggml-sm11 Q4 wire-up for on-device weights; until then GPU decision = stories15M sm11 full-forward, CPU coder-class = SmolLM2 Q4.

See [bench-decision/SUMMARY.md](bench-decision/SUMMARY.md).
