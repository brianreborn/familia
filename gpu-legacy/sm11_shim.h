/* C ABI shim: CUDA 6.5 / sm_11 kernels callable from plain C (or a modern-compiler llama.cpp/ggml build). */
#ifndef SM11_SHIM_H
#define SM11_SHIM_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Upload a host weight blob [base, base+nbytes) to VRAM once. 0 = ok. */
int sm11_register(const void* base, size_t nbytes);
/* xout[d] = W[d,n] @ x[n]; W must lie inside the registered blob. 0 = ok, else caller falls back to CPU. */
int sm11_matmul(float* xout, const float* x, const float* w, int n, int d);
#ifdef __cplusplus
}
#endif
#endif
