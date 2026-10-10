# gpu-legacy: LLM inference on qodesh's GeForce 8600 GT (sm_11, 256 MiB, driver 341.92)

Status: **working, GPU gives the same answer but runs slower than the CPU.** Greedy output matches the CPU output exactly.

## How it works (no CUDA toolkit or MSVC needed)
- `matvec_sm11.ptx`: matvec kernel written by hand in PTX 4.1, `.target sm_11`. The driver's built-in compiler turns it into GPU code at runtime.
- `sm11_shim.c`: a plain C interface (`sm11_register`, `sm11_matmul`) that loads `nvcuda.dll` at runtime through the CUDA driver API. It keeps as much of the weight file in VRAM as fits and streams the rest through a 4 MiB staging buffer. If anything fails it falls back to the CPU. Any modern compiler can link it, so it is the planned hook for a ggml backend.
- `run.c` / `win.c`: karpathy/llama2.c with its `matmul` routed to the shim when `FAMILIA_GPU=1`. Setting `SM11_NO_STREAM=1` keeps the tensors that aren't in VRAM on the CPU. `SM11_RESIDENT_MIB` caps how much stays in VRAM.
- `sm11_shim.cu` + `build.bat`: the same interface for nvcc 6.5 + VS2013. **Not built**, because qodesh has no VS2013 `cl.exe` (the VS 12.0 folder is empty).
- Build: `build-gcc.bat` (portable WinLibs gcc 16.1 at `E:\temp\tools\mingw64`, sha256 verified).

## Results (stories15M fp32, greedy, 200 tokens, 2 threads, Athlon II X2 B24)
| runtime | tok/s |
|---|---|
| llama2.c CPU (this exe, FAMILIA_GPU=0) | 68–71 |
| GPU, 40 MiB in VRAM + 17 MiB streamed per token (56 MiB VRAM free) | 17.4 |
| GPU, all 57 MiB in VRAM (91 MiB free on that run) | 18.5 |
| llama.cpp b11540 win-cpu-x64, stories15M F32, tg128 | 68.5 |
| llama.cpp b11540 win-cpu-x64, stories15M Q4_0, tg128 / pp64 | 201 / 487 |

The bottleneck is overhead on each of the ~43 matmul calls per token: a blocking H2D copy, a launch, and a D2H copy under WDDM. Memory bandwidth is not the limit. Next steps: keep activations on the GPU (rmsnorm/rope/softmax/silu kernels) and copy back only the logits; batch the prompt (pp), where the GPU matvec becomes a matmul; then a ggml backend that uses this shim.

Only 56–91 MiB of the 256 MiB VRAM is free, because the card also drives the desktop.
