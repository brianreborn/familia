# ggml-sm11

Minimal ggml / llama.cpp hook for the `sm11_shim` legacy-GPU path.

## Integration plan (feat/qodesh-legacy-gpu)
1. Build llama.cpp with WinLibs gcc (CPU, no AVX required — Athlon II).
2. Link `sm11_shim.c` + load `kernels.ptx`.
3. In the CPU `MUL_MAT` / `MUL_MAT_ID` forward (F32 weights), call `ggml_sm11_try_mul_mat` when
   `SM11_OFFLOAD=1` and the weight tensor is contiguous F32.
4. For always-active decision models: prefer the llama2.c full-forward path (already faster to iterate).
5. For **partial offload of a larger active model**: leave the graph on CPU, send selected large
   `MUL_MAT`s (FFN up/down, output) through sm11. Activations bounce once per offloaded op —
   still useful when the CPU is busy with another model.

## Status
Scaffolding. Next commit on qodesh: wire into b11540 `ggml-cpu` mul_mat and measure stories15M Q4_0
(dequant on CPU, F32 accumulate offload) vs F32.
