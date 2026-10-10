// CUDA 6.5, -arch=sm_11 (GeForce 8600 GT). No C++11, no doubles, no warp shuffles.
#include <stdio.h>
#include <cuda_runtime.h>
#include "sm11_shim.h"

#define BLOCK 128
static const char* g_hbase = 0;
static char* g_dbase = 0;
static size_t g_nbytes = 0;
static float* g_dx = 0; static float* g_dy = 0; static int g_cap = 0;

__global__ void k_matvec(float* y, const float* x, const float* W, int n, int d) {
    __shared__ float s[BLOCK];
    int row = blockIdx.x + blockIdx.y * gridDim.x;
    if (row >= d) return;
    const float* w = W + (size_t)row * n;
    float acc = 0.0f;
    for (int j = threadIdx.x; j < n; j += BLOCK) acc += w[j] * x[j];
    s[threadIdx.x] = acc;
    __syncthreads();
    for (int st = BLOCK / 2; st > 0; st >>= 1) {
        if (threadIdx.x < st) s[threadIdx.x] += s[threadIdx.x + st];
        __syncthreads();
    }
    if (threadIdx.x == 0) y[row] = s[0];
}

static int ensure(int cap) {
    if (cap <= g_cap) return 0;
    if (g_dx) cudaFree(g_dx);
    if (g_dy) cudaFree(g_dy);
    if (cudaMalloc((void**)&g_dx, cap * sizeof(float)) != cudaSuccess) return -1;
    if (cudaMalloc((void**)&g_dy, cap * sizeof(float)) != cudaSuccess) return -1;
    g_cap = cap; return 0;
}

extern "C" int sm11_register(const void* base, size_t nbytes) {
    cudaDeviceProp p; int dev = 0;
    if (cudaGetDeviceCount(&dev) != cudaSuccess || dev == 0) { fprintf(stderr, "sm11: no CUDA device\n"); return -1; }
    cudaGetDeviceProperties(&p, 0);
    size_t fr = 0, tot = 0; cudaMemGetInfo(&fr, &tot);
    fprintf(stderr, "sm11: %s cc%d.%d vram free %u/%u MiB, blob %u MiB\n", p.name, p.major, p.minor,
            (unsigned)(fr >> 20), (unsigned)(tot >> 20), (unsigned)(nbytes >> 20));
    if (nbytes + (8u << 20) > fr) { fprintf(stderr, "sm11: blob does not fit VRAM, cpu fallback\n"); return -1; }
    if (cudaMalloc((void**)&g_dbase, nbytes) != cudaSuccess) return -1;
    if (cudaMemcpy(g_dbase, base, nbytes, cudaMemcpyHostToDevice) != cudaSuccess) { cudaFree(g_dbase); g_dbase = 0; return -1; }
    g_hbase = (const char*)base; g_nbytes = nbytes;
    return ensure(65536);
}

extern "C" int sm11_matmul(float* xout, const float* x, const float* w, int n, int d) {
    const char* wp = (const char*)w;
    if (!g_dbase || wp < g_hbase || wp + (size_t)n * d * sizeof(float) > g_hbase + g_nbytes) return -1;
    int need = n > d ? n : d;
    if (ensure(need)) return -1;
    const float* dW = (const float*)(g_dbase + (wp - g_hbase));
    cudaMemcpy(g_dx, x, n * sizeof(float), cudaMemcpyHostToDevice);
    dim3 grid(d < 65535 ? d : 65535, (d + 65534) / 65535);
    k_matvec<<<grid, BLOCK>>>(g_dy, g_dx, dW, n, d);
    if (cudaMemcpy(xout, g_dy, d * sizeof(float), cudaMemcpyDeviceToHost) != cudaSuccess) return -1;
    return 0;
}
