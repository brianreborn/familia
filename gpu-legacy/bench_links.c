/* bench_links.c: per-link bandwidth/latency of a legacy NVIDIA GPU via the CUDA driver API only
 * (dlopen libcuda, _v2 symbols present since CUDA 3.2, so it runs on the 340.108 legacy driver).
 * No kernels, no toolkit needed. Prints one JSON line per measurement (docs/design/topology-bandwidth-prototype.md).
 * Build: cc -O2 -o bench_links bench_links.c -ldl     Run: ./bench_links [MiB=32] [reps=8] */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
typedef int CUr; typedef unsigned long long Dp; typedef void *Ctx, *Str;
static CUr (*Init)(unsigned), (*DevGet)(int *, int), (*DevName)(char *, int, int), (*Create)(Ctx *, unsigned, int),
  (*Alloc)(Dp *, size_t), (*Free)(Dp), (*AllocHost)(void **, size_t), (*FreeHost)(void *),
  (*HtoD)(Dp, const void *, size_t), (*DtoH)(void *, Dp, size_t), (*DtoD)(Dp, Dp, size_t),
  (*HtoDA)(Dp, const void *, size_t, Str), (*DtoHA)(void *, Dp, size_t, Str), (*SCreate)(Str *, unsigned),
  (*Sync)(void), (*Attr)(int *, int, int), (*MemInfo)(size_t *, size_t *);
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
#define L(f, s) if (!(f = dlsym(h, s))) { fprintf(stderr, "missing %s\n", s); return 2; }
#define C(x) do { CUr r_ = (x); if (r_) { fprintf(stderr, "%s = %d\n", #x, r_); return 3; } } while (0)
static void out(const char *link, const char *how, size_t bytes, int reps, double s) {
  printf("{\"link\":\"%s\",\"how\":\"%s\",\"bytes\":%zu,\"reps\":%d,\"sec\":%.6f,\"GBps\":%.3f,\"us_per_op\":%.2f}\n",
         link, how, bytes, reps, s, bytes * (double)reps / s / 1e9, s / reps * 1e6);
}
int main(int argc, char **argv) {
  size_t mib = argc > 1 ? atoi(argv[1]) : 32, n = mib << 20; int reps = argc > 2 ? atoi(argv[2]) : 8;
  void *h = dlopen("libcuda.so.1", RTLD_NOW); if (!h) { fprintf(stderr, "%s\n", dlerror()); return 2; }
  L(Init, "cuInit") L(DevGet, "cuDeviceGet") L(DevName, "cuDeviceGetName") L(Create, "cuCtxCreate_v2")
  L(Alloc, "cuMemAlloc_v2") L(Free, "cuMemFree_v2") L(AllocHost, "cuMemAllocHost_v2") L(FreeHost, "cuMemFreeHost")
  L(HtoD, "cuMemcpyHtoD_v2") L(DtoH, "cuMemcpyDtoH_v2") L(DtoD, "cuMemcpyDtoD_v2") L(HtoDA, "cuMemcpyHtoDAsync_v2")
  L(DtoHA, "cuMemcpyDtoHAsync_v2") L(SCreate, "cuStreamCreate") L(Sync, "cuCtxSynchronize")
  L(Attr, "cuDeviceGetAttribute") L(MemInfo, "cuMemGetInfo_v2")
  int dev; Ctx ctx; char name[128]; C(Init(0)); C(DevGet(&dev, 0)); C(DevName(name, sizeof name, dev)); C(Create(&ctx, 0, dev));
  int ce = -1, ov = -1; Attr(&ce, 40 /*ASYNC_ENGINE_COUNT*/, dev); Attr(&ov, 15 /*GPU_OVERLAP*/, dev);
  size_t fr, tot; MemInfo(&fr, &tot);
  printf("{\"device\":\"%s\",\"vram_total\":%zu,\"vram_free\":%zu,\"async_engines\":%d,\"gpu_overlap\":%d}\n", name, tot, fr, ce, ov);
  Dp a, b; C(Alloc(&a, n)); C(Alloc(&b, n)); void *pin, *pin2; C(AllocHost(&pin, n)); C(AllocHost(&pin2, n));
  char *pg = malloc(n); memset(pg, 1, n); memset(pin, 1, n);
  double t; int i; Str s1, s2; C(SCreate(&s1, 0)); C(SCreate(&s2, 0));
  HtoD(a, pin, n); Sync();
  t = now(); for (i = 0; i < reps; i++) C(HtoD(a, pin, n)); Sync(); out("pcie_h2d", "pinned", n, reps, now() - t);
  t = now(); for (i = 0; i < reps; i++) C(DtoH(pin, a, n)); Sync(); out("pcie_d2h", "pinned", n, reps, now() - t);
  t = now(); for (i = 0; i < reps; i++) C(HtoD(a, pg, n)); Sync(); out("pcie_h2d", "pageable", n, reps, now() - t);
  t = now(); for (i = 0; i < reps; i++) C(DtoH(pg, a, n)); Sync(); out("pcie_d2h", "pageable", n, reps, now() - t);
  t = now(); for (i = 0; i < reps * 4; i++) C(DtoD(b, a, n)); Sync(); out("vram_copy", "dtod(read+write=2x bytes)", 2 * n, reps * 4, now() - t);
  t = now(); for (i = 0; i < 1000; i++) C(HtoD(a, pin, 4)); Sync(); out("pcie_h2d", "latency_4B", 4, 1000, now() - t);
  t = now(); for (i = 0; i < 1000; i++) C(DtoH(pin, a, 4)); out("pcie_d2h", "latency_4B", 4, 1000, now() - t);
  t = now(); for (i = 0; i < 1000; i++) Sync(); out("sync", "ctx_sync_empty", 0, 1000, now() - t);
  /* overlap: H2D and D2H on two streams together vs serial; ratio ~1 = one copy engine (no duplex) */
  t = now(); for (i = 0; i < reps; i++) { HtoDA(a, pin, n, s1); DtoHA(pin2, b, n, s2); } Sync(); double par = now() - t;
  t = now(); for (i = 0; i < reps; i++) { HtoDA(a, pin, n, s1); DtoHA(pin2, b, n, s1); } Sync(); double ser = now() - t;
  printf("{\"link\":\"copy_engine\",\"how\":\"h2d+d2h two streams vs one\",\"bytes\":%zu,\"reps\":%d,\"parallel_s\":%.6f,\"serial_s\":%.6f,\"overlap_ratio\":%.3f}\n",
         2 * n, reps, par, ser, ser / par);
  Free(a); Free(b); FreeHost(pin); FreeHost(pin2); free(pg); return 0;
}
