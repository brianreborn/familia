/* Pluggable legacy-GPU backend for usually-ACTIVE models (decision, draft, partial offload).
 * Implementations: sm11 (CUDA driver / GeForce 8/9), later: dxcs (D3D11 FL10), ocl11, vulkan1.
 * Contract: keep activations on-device; host only feeds tokens and reads logits (or accepts
 * partial tensor offload of a larger CPU model via offload_mul_mat). */
#ifndef LEGACY_GPU_H
#define LEGACY_GPU_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    int dim, hidden_dim, n_layers, n_heads, n_kv_heads, vocab_size, seq_len;
} LgpuConfig;
typedef struct LgpuBackend {
    const char* name;           /* "sm11", "dxcs", ... */
    int (*probe)(char* desc, int n);                 /* 0 if usable */
    int (*register_weights)(const void* base, size_t nbytes);
    int (*init)(const LgpuConfig* cfg, float** weight_ptrs /* see sm11_init */);
    int (*forward)(int token, int pos, float* logits_out);
    void (*reset_kv)(void);
    /* Partial offload hook for a larger active model whose body stays on CPU/host: */
    int (*offload_mul_mat)(float* y, const float* x, const float* w, int n, int d);
} LgpuBackend;
const LgpuBackend* lgpu_sm11(void);
#ifdef __cplusplus
}
#endif
#endif
