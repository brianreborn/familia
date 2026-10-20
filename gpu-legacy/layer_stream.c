/* layer_stream.c: AirLLM-style layer-at-a-time streaming loop on a legacy NVIDIA GPU (#90).
 * Per simulated token, every layer's weights are copied host(pinned)->VRAM into one of two
 * VRAM slots, then read once on the device (DtoD in 16 MiB pieces into a scratch buffer, standing in for the
 * layer's weight read). Only two layer slots live in VRAM, so models far larger than VRAM run.
 * CUDA driver API via dlopen only, so it runs on 340.108; no kernels, no toolkit. It measures
 * the transport bound of the mode, not model math. Prints one JSON line.
 * Build: cc -O2 -o layer_stream layer_stream.c -ldl   Run: ./layer_stream LAYER_MIB N_LAYERS [TOKENS=3] */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
typedef int CUr; typedef unsigned long long Dp; typedef void *Ctx, *Str;
static CUr (*Init)(unsigned), (*DevGet)(int *, int), (*Create)(Ctx *, unsigned, int), (*Alloc)(Dp *, size_t),
  (*AllocHost)(void **, size_t), (*HtoDA)(Dp, const void *, size_t, Str), (*DtoDA)(Dp, Dp, size_t, Str),
  (*SCreate)(Str *, unsigned), (*Sync)(void);
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
#define L(f, s) if (!(f = dlsym(h, s))) { fprintf(stderr, "missing %s\n", s); return 2; }
#define C(x) do { CUr r_ = (x); if (r_) { fprintf(stderr, "%s = %d\n", #x, r_); return 3; } } while (0)
int main(int argc, char **argv) {
  if (argc < 3) { fprintf(stderr, "usage: layer_stream LAYER_MIB N_LAYERS [TOKENS]\n"); return 1; }
  double lm = atof(argv[1]); size_t n = (size_t)(lm * 1048576); int nl = atoi(argv[2]), tk = argc > 3 ? atoi(argv[3]) : 3;
  void *h = dlopen("libcuda.so.1", RTLD_NOW); if (!h) { fprintf(stderr, "%s\n", dlerror()); return 2; }
  L(Init, "cuInit") L(DevGet, "cuDeviceGet") L(Create, "cuCtxCreate_v2") L(Alloc, "cuMemAlloc_v2")
  L(AllocHost, "cuMemAllocHost_v2") L(HtoDA, "cuMemcpyHtoDAsync_v2") L(DtoDA, "cuMemcpyDtoDAsync_v2")
  L(SCreate, "cuStreamCreate") L(Sync, "cuCtxSynchronize")
  int dev; Ctx c; Str s[2]; Dp slot[2], scratch; void *host;
  C(Init(0)); C(DevGet(&dev, 0)); C(Create(&c, 0, dev)); C(SCreate(&s[0], 0)); C(SCreate(&s[1], 0));
  C(Alloc(&slot[0], n)); C(Alloc(&slot[1], n)); size_t sc = n < (16u << 20) ? n : (16u << 20); C(Alloc(&scratch, sc)); C(AllocHost(&host, n));
  /* host weights: one pinned layer buffer reused for every layer (RAM-resident model; the host
     read side is measured separately as host_ram) */
  for (int w = 0; w < 2; w++) { C(HtoDA(slot[w], host, n, s[w])); } C(Sync());
  double t = now();
  for (int k = 0; k < tk; k++)
    for (int l = 0; l < nl; l++) { int w = l & 1; C(HtoDA(slot[w], host, n, s[w])); for (size_t o = 0; o < n; o += sc) C(DtoDA(scratch, slot[w] + o, n - o < sc ? n - o : sc, s[w])); }
  C(Sync()); t = now() - t;
  printf("{\"link\":\"layer_stream\",\"how\":\"htod+dtod per layer, 2 slots\",\"layer_bytes\":%zu,\"layers\":%d,"
         "\"tokens\":%d,\"sec\":%.6f,\"tok_s\":%.4f,\"bytes_per_tok\":%zu}\n", n, nl, tk, t, tk / t, n * (size_t)nl);
  return 0;
}
