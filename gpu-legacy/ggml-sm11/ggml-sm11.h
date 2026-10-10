#pragma once
/* Minimal ggml backend for legacy GPUs via sm11_shim (CUDA driver / GeForce 8–9).
 * Offloads MUL_MAT (F32) when the weight matrix is registered/resident; else CPU.
 * Plug point for other LgpuBackend implementations (dxcs, ocl11). */
#ifdef __cplusplus
extern "C" {
#endif
struct ggml_backend;
struct ggml_backend_buffer_type;
struct ggml_backend_device;
/* Returns a backend that routes MUL_MAT through sm11_matmul when FAMILIA_GPU/SM11 is live. */
struct ggml_backend * ggml_backend_sm11_init(void);
const char * ggml_backend_sm11_name(void);
int ggml_backend_sm11_probe(char * desc, int n);
#ifdef __cplusplus
}
#endif
