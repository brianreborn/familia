/* sm11_shim.c - C ABI shim to the GeForce 8600 GT (sm_11) via the CUDA *driver* API in nvcuda.dll.
 * No CUDA toolkit or MSVC needed: nvcuda.dll is loaded at runtime and the PTX below is JIT-compiled by
 * driver 341.92. Any modern compiler (mingw-w64 gcc, clang, MSVC) can link this, which is also the hook
 * for a ggml backend. Same API as sm11_shim.cu (nvcc 6.5 variant). */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "sm11_shim.h"

typedef int CUresult; typedef int CUdevice; typedef void* CUcontext; typedef void* CUmodule; typedef void* CUfunction;
typedef unsigned long long CUdeviceptr;
static CUresult (__stdcall *p_cuInit)(unsigned);
static CUresult (__stdcall *p_cuDeviceGet)(CUdevice*, int);
static CUresult (__stdcall *p_cuDeviceGetName)(char*, int, CUdevice);
static CUresult (__stdcall *p_cuDeviceComputeCapability)(int*, int*, CUdevice);
static CUresult (__stdcall *p_cuCtxCreate)(CUcontext*, unsigned, CUdevice);
static CUresult (__stdcall *p_cuModuleLoadDataEx)(CUmodule*, const void*, unsigned, int*, void**);
static CUresult (__stdcall *p_cuModuleGetFunction)(CUfunction*, CUmodule, const char*);
static CUresult (__stdcall *p_cuMemAlloc)(CUdeviceptr*, size_t);
static CUresult (__stdcall *p_cuMemGetInfo)(size_t*, size_t*);
static CUresult (__stdcall *p_cuMemcpyHtoD)(CUdeviceptr, const void*, size_t);
static CUresult (__stdcall *p_cuMemcpyDtoH)(void*, CUdeviceptr, size_t);
static CUresult (__stdcall *p_cuLaunchKernel)(CUfunction, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, void*, void**, void**);

static const char* PTX =
"// Hand-written PTX for GeForce 8600 GT (sm_11), JIT-compiled by driver 341.92 (no nvcc / host compiler needed).\n"
"// y[row] = dot(W[row,:], x); one 128-thread block per output row.\n"
".version 4.1\n"
".target sm_11\n"
".address_size 64\n"
"\n"
".visible .entry matvec(.param .u64 py, .param .u64 px, .param .u64 pw, .param .u32 pn, .param .u32 pd)\n"
"{\n"
"  .reg .u32 %r<12>;\n"
"  .reg .u64 %rd<14>;\n"
"  .reg .f32 %f<8>;\n"
"  .reg .pred %p<5>;\n"
"  .shared .align 4 .f32 sm[128];\n"
"\n"
"  ld.param.u64 %rd1, [py];\n"
"  ld.param.u64 %rd2, [px];\n"
"  ld.param.u64 %rd3, [pw];\n"
"  ld.param.u32 %r1, [pn];\n"
"  ld.param.u32 %r2, [pd];\n"
"  mov.u32 %r3, %ctaid.x;\n"
"  setp.ge.u32 %p1, %r3, %r2;\n"
"  @%p1 bra DONE;\n"
"  mov.u32 %r4, %tid.x;\n"
"  mul.wide.u32 %rd4, %r3, %r1;\n"
"  shl.b64 %rd4, %rd4, 2;\n"
"  add.u64 %rd4, %rd3, %rd4;\n"
"  mov.f32 %f1, 0f00000000;\n"
"  mov.u32 %r5, %r4;\n"
"LOOP:\n"
"  setp.ge.u32 %p2, %r5, %r1;\n"
"  @%p2 bra RED;\n"
"  mul.wide.u32 %rd5, %r5, 4;\n"
"  add.u64 %rd6, %rd4, %rd5;\n"
"  add.u64 %rd7, %rd2, %rd5;\n"
"  ld.global.f32 %f2, [%rd6];\n"
"  ld.global.f32 %f3, [%rd7];\n"
"  mad.f32 %f1, %f2, %f3, %f1;\n"
"  add.u32 %r5, %r5, 128;\n"
"  bra LOOP;\n"
"RED:\n"
"  mov.u64 %rd8, sm;\n"
"  mul.wide.u32 %rd9, %r4, 4;\n"
"  add.u64 %rd9, %rd8, %rd9;\n"
"  st.shared.f32 [%rd9], %f1;\n"
"  mov.u32 %r6, 64;\n"
"RLOOP:\n"
"  bar.sync 0;\n"
"  setp.ge.u32 %p3, %r4, %r6;\n"
"  @%p3 bra RSKIP;\n"
"  mul.wide.u32 %rd10, %r6, 4;\n"
"  add.u64 %rd10, %rd9, %rd10;\n"
"  ld.shared.f32 %f4, [%rd9];\n"
"  ld.shared.f32 %f5, [%rd10];\n"
"  add.f32 %f4, %f4, %f5;\n"
"  st.shared.f32 [%rd9], %f4;\n"
"RSKIP:\n"
"  shr.u32 %r6, %r6, 1;\n"
"  setp.ne.u32 %p4, %r6, 0;\n"
"  @%p4 bra RLOOP;\n"
"  setp.ne.u32 %p3, %r4, 0;\n"
"  @%p3 bra DONE;\n"
"  ld.shared.f32 %f6, [%rd8];\n"
"  mul.wide.u32 %rd11, %r3, 4;\n"
"  add.u64 %rd11, %rd1, %rd11;\n"
"  st.global.f32 [%rd11], %f6;\n"
"DONE:\n"
"  exit;\n"
"}\n";

static CUfunction g_fn; static const char* g_hbase; static size_t g_nbytes;
static CUdeviceptr g_dbase, g_dx, g_dy, g_stage; static int g_cap; static size_t g_resident, g_stage_bytes;
static unsigned long long g_streamed;
#define LOAD(n, s) do { *(FARPROC*)&p_##n = GetProcAddress(h, s); if (!p_##n) { fprintf(stderr, "sm11: missing %s\n", s); return -1; } } while (0)
#define CK(e) do { CUresult _r = (e); if (_r) { fprintf(stderr, "sm11: %s -> %d\n", #e, _r); return -1; } } while (0)

static int ensure(int cap) {
    if (cap <= g_cap) return 0;
    CK(p_cuMemAlloc(&g_dx, (size_t)cap * 4)); CK(p_cuMemAlloc(&g_dy, (size_t)cap * 4));
    g_cap = cap; return 0;
}

int sm11_register(const void* base, size_t nbytes) {
    HMODULE h = LoadLibraryA("nvcuda.dll");
    if (!h) { fprintf(stderr, "sm11: nvcuda.dll not found\n"); return -1; }
    LOAD(cuInit, "cuInit"); LOAD(cuDeviceGet, "cuDeviceGet"); LOAD(cuDeviceGetName, "cuDeviceGetName");
    LOAD(cuDeviceComputeCapability, "cuDeviceComputeCapability"); LOAD(cuCtxCreate, "cuCtxCreate_v2");
    LOAD(cuModuleLoadDataEx, "cuModuleLoadDataEx"); LOAD(cuModuleGetFunction, "cuModuleGetFunction");
    LOAD(cuMemAlloc, "cuMemAlloc_v2"); LOAD(cuMemGetInfo, "cuMemGetInfo_v2");
    LOAD(cuMemcpyHtoD, "cuMemcpyHtoD_v2"); LOAD(cuMemcpyDtoH, "cuMemcpyDtoH_v2"); LOAD(cuLaunchKernel, "cuLaunchKernel");
    CUdevice dev; CUcontext ctx; CUmodule mod; char name[128]; int ma = 0, mi = 0; size_t fr = 0, tot = 0;
    CK(p_cuInit(0)); CK(p_cuDeviceGet(&dev, 0)); CK(p_cuDeviceGetName(name, sizeof name, dev));
    CK(p_cuDeviceComputeCapability(&ma, &mi, dev)); CK(p_cuCtxCreate(&ctx, 0, dev));
    char log[4096] = {0}; int opts[2] = {5 /*CU_JIT_ERROR_LOG_BUFFER*/, 6 /*CU_JIT_ERROR_LOG_BUFFER_SIZE_BYTES*/};
    void* vals[2] = {log, (void*)(size_t)sizeof log};
    CUresult r = p_cuModuleLoadDataEx(&mod, PTX, 2, opts, vals);
    if (r) { fprintf(stderr, "sm11: PTX JIT failed %d: %s\n", r, log); return -1; }
    CK(p_cuModuleGetFunction(&g_fn, mod, "matvec"));
    CK(p_cuMemGetInfo(&fr, &tot));
    fprintf(stderr, "sm11: %s cc%d.%d vram free %u/%u MiB, weights %u MiB\n", name, ma, mi,
            (unsigned)(fr >> 20), (unsigned)(tot >> 20), (unsigned)(nbytes >> 20));
    /* Resident prefix of the weight blob (token embedding / classifier sits first) + a staging buffer
     * through which the remaining tensors are streamed from host RAM per matmul. */
    g_stage_bytes = 4u << 20;
    size_t budget = fr > (g_stage_bytes + (12u << 20)) ? fr - g_stage_bytes - (12u << 20) : 0;
    const char* cap = getenv("SM11_RESIDENT_MIB");
    if (cap) { size_t c = (size_t)atoi(cap) << 20; if (c < budget) budget = c; }
    g_resident = nbytes < budget ? nbytes : budget;
    CK(p_cuMemAlloc(&g_stage, g_stage_bytes));
    if (g_resident) { CK(p_cuMemAlloc(&g_dbase, g_resident)); CK(p_cuMemcpyHtoD(g_dbase, base, g_resident)); }
    fprintf(stderr, "sm11: resident %u MiB, streamed %u MiB via %u MiB staging\n", (unsigned)(g_resident >> 20),
            (unsigned)((nbytes - g_resident) >> 20), (unsigned)(g_stage_bytes >> 20));
    g_hbase = (const char*)base; g_nbytes = nbytes;
    return ensure(65536);
}

int sm11_matmul(float* xout, const float* x, const float* w, int n, int d) {
    const char* wp = (const char*)w;
    if (!g_fn || wp < g_hbase || wp + (size_t)n * d * 4 > g_hbase + g_nbytes) return -1;
    if (ensure(n > d ? n : d)) return -1;
    unsigned un = (unsigned)n;
    CK(p_cuMemcpyHtoD(g_dx, x, (size_t)n * 4));
    size_t off = (size_t)(wp - g_hbase), rowb = (size_t)n * 4;
    if (off + rowb * d <= g_resident) {
        CUdeviceptr dW = g_dbase + off; unsigned ud = (unsigned)d;
        void* args[5] = {&g_dy, &g_dx, &dW, &un, &ud};
        CK(p_cuLaunchKernel(g_fn, ud, 1, 1, 128, 1, 1, 0, 0, args, 0));
    } else if (getenv("SM11_NO_STREAM")) {
        return -1; /* hybrid: non-resident tensors stay on CPU */
    } else {
        int rows = (int)(g_stage_bytes / rowb), r0;
        if (rows < 1) return -1;
        for (r0 = 0; r0 < d; r0 += rows) {
            int nr = d - r0 < rows ? d - r0 : rows; unsigned unr = (unsigned)nr;
            CUdeviceptr dy = g_dy + (CUdeviceptr)r0 * 4;
            CK(p_cuMemcpyHtoD(g_stage, wp + rowb * r0, rowb * nr));
            g_streamed += rowb * nr;
            void* args[5] = {&dy, &g_dx, &g_stage, &un, &unr};
            CK(p_cuLaunchKernel(g_fn, unr, 1, 1, 128, 1, 1, 0, 0, args, 0));
        }
    }
    CK(p_cuMemcpyDtoH(xout, g_dy, (size_t)d * 4));
    return 0;
}
