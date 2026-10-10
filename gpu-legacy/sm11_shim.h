/* C ABI: CUDA sm_11 forward pass. Activations + KV stay on device; only logits return. */
#ifndef SM11_SHIM_H
#define SM11_SHIM_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    int dim, hidden_dim, n_layers, n_heads, n_kv_heads, vocab_size, seq_len;
} Sm11Config;

/* Register host weight blob (llama2.c layout after Config). 0 = ok. */
int sm11_register(const void* base, size_t nbytes);
/* Compat: single matmul; prefer sm11_init + sm11_forward. */
int sm11_matmul(float* xout, const float* x, const float* w, int n, int d);

/* Bind config + weight pointers (host addresses inside the registered blob). */
int sm11_init(const Sm11Config* cfg,
              float* token_embedding_table, float* rms_att_weight, float* rms_ffn_weight,
              float* wq, float* wk, float* wv, float* wo,
              float* w1, float* w2, float* w3, float* rms_final_weight, float* wcls);
/* One token forward; writes vocab_size logits to host. */
int sm11_forward(int token, int pos, float* logits_out);
void sm11_reset_kv(void);
/* Quantized matvecs (GGML block layout). n must be multiple of 32. */
int sm11_q4_matmul(float* xout, const float* x, const void* w_q4, int n, int d);
int sm11_q8_matmul(float* xout, const float* x, const void* w_q8, int n, int d);
/* Batch up to 8 F32 matvecs in one launch (grid.y = njobs). Each job streams W if needed. */
typedef struct { float* y; const float* x; const float* w; int n, d; } Sm11Job;
int sm11_matvec_batch(const Sm11Job* jobs, int njobs);

int sm11_wmatvec(int kind, float* y, const float* x, const void* w, int n, int d);
size_t sm11_wcache_bytes(void);
#ifdef __cplusplus
}
#endif
#endif
