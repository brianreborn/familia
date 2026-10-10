/* Full forward pass on GeForce 8600 GT (sm_11) via CUDA driver API + hand-written PTX.
 * Activations + KV stay on device; host copies only logits. Designed as the sm11
 * implementation of legacy_gpu.h for always-active decision/draft models and partial offload. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
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
static CUresult (__stdcall *p_cuMemFree)(CUdeviceptr);
static CUresult (__stdcall *p_cuMemGetInfo)(size_t*, size_t*);
static CUresult (__stdcall *p_cuMemcpyHtoD)(CUdeviceptr, const void*, size_t);
static CUresult (__stdcall *p_cuMemcpyDtoH)(void*, CUdeviceptr, size_t);
static CUresult (__stdcall *p_cuMemcpyDtoD)(CUdeviceptr, CUdeviceptr, size_t);
static CUresult (__stdcall *p_cuLaunchKernel)(CUfunction, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, void*, void**, void**);
static CUresult (__stdcall *p_cuCtxSynchronize)(void);


/* ---- async completion: pinned staging + event polling (no cuCtxSynchronize in hot paths) ----
   One CUDA context, default stream: work is ordered on the device. The host never blocks in the
   driver; it records an event and polls cuEventQuery, yielding the core between polls. */
typedef void* CUevent_;
static CUresult (__stdcall *p_cuMemHostAlloc)(void**, size_t, unsigned);
static CUresult (__stdcall *p_cuMemcpyHtoDAsync)(CUdeviceptr, const void*, size_t, void*);
static CUresult (__stdcall *p_cuMemcpyDtoHAsync)(void*, CUdeviceptr, size_t, void*);
static CUresult (__stdcall *p_cuEventCreate)(CUevent_*, unsigned);
static CUresult (__stdcall *p_cuEventRecord)(CUevent_, void*);
static CUresult (__stdcall *p_cuEventQuery)(CUevent_);
static CUresult (__stdcall *p_cuEventSynchronize)(CUevent_);
static CUevent_ g_fev; static int g_async = 0;
static unsigned char* g_pin; static size_t g_pinsz = 0, g_pinoff = 0;
volatile long long g_sm11_polls = 0, g_sm11_fences = 0;
static void async_init(HMODULE h) {
    p_cuMemHostAlloc = (void*)GetProcAddress(h, "cuMemHostAlloc");
    p_cuMemcpyHtoDAsync = (void*)GetProcAddress(h, "cuMemcpyHtoDAsync_v2");
    p_cuMemcpyDtoHAsync = (void*)GetProcAddress(h, "cuMemcpyDtoHAsync_v2");
    p_cuEventCreate = (void*)GetProcAddress(h, "cuEventCreate");
    p_cuEventRecord = (void*)GetProcAddress(h, "cuEventRecord");
    p_cuEventQuery = (void*)GetProcAddress(h, "cuEventQuery");
    p_cuEventSynchronize = (void*)GetProcAddress(h, "cuEventSynchronize");
    if (!p_cuMemHostAlloc || !p_cuMemcpyHtoDAsync || !p_cuMemcpyDtoHAsync || !p_cuEventCreate || !p_cuEventRecord || !p_cuEventQuery) return;
    if (getenv("SM11_SYNC") && atoi(getenv("SM11_SYNC"))) return;      /* opt-out: legacy blocking path */
    g_pinsz = (size_t)1 << 20;   /* 1 MiB pinned staging (x in, y out) */
    if (p_cuMemHostAlloc((void**)&g_pin, g_pinsz, 0) || p_cuEventCreate(&g_fev, 2 /*DISABLE_TIMING*/)) { g_pin = 0; return; }
    g_async = 1;
    fprintf(stderr, "sm11: async path on (pinned %u KiB staging, event polling, no ctx sync)\n", (unsigned)(g_pinsz >> 10));
}
/* wait for all enqueued device work without blocking in the driver */
static int sm11_fence(void) {
    if (!g_async) return p_cuCtxSynchronize() ? -1 : 0;
    if (p_cuEventRecord(g_fev, 0)) return -1;
    CUresult r; g_sm11_fences++;
    int k = 0;
    while ((r = p_cuEventQuery(g_fev)) == 600 /*NOT_READY*/) { g_sm11_polls++; if (++k > 64 && p_cuEventSynchronize) { r = p_cuEventSynchronize(g_fev); break; } YieldProcessor(); }
    g_pinoff = 0;                     /* all staged copies have completed */
    return r ? -1 : 0;
}
static unsigned char* pin_take(size_t n) {
    n = (n + 255) & ~(size_t)255;
    if (!g_async || g_pinoff + n > g_pinsz) return 0;
    unsigned char* p = g_pin + g_pinoff; g_pinoff += n; return p;
}
/* enqueue H2D without waiting: copy into pinned staging, async DMA. Falls back to blocking copy. */
static int sm11_htod(CUdeviceptr d, const void* h, size_t n) {
    unsigned char* p = pin_take(n);
    if (!p) return p_cuMemcpyHtoD(d, h, n) ? -1 : 0;
    memcpy(p, h, n); return p_cuMemcpyHtoDAsync(d, p, n, 0) ? -1 : 0;
}
/* D2H results of everything enqueued so far: async DMA into pinned, one fence, then memcpy out. */
typedef struct { void* dst; CUdeviceptr src; size_t n; unsigned char* pin; } Sm11Out;
static int sm11_dtoh_many(Sm11Out* o, int k) {
    int i;
    if (!g_async) { if (p_cuCtxSynchronize()) return -1; for (i = 0; i < k; i++) if (p_cuMemcpyDtoH(o[i].dst, o[i].src, o[i].n)) return -1; return 0; }
    for (i = 0; i < k; i++) { o[i].pin = pin_take(o[i].n);
        if (!o[i].pin) { if (sm11_fence()) return -1; o[i].pin = pin_take(o[i].n); }
        if (!o[i].pin) { if (p_cuMemcpyDtoH(o[i].dst, o[i].src, o[i].n)) return -1; continue; }   /* too big for staging */
        if (p_cuMemcpyDtoHAsync(o[i].pin, o[i].src, o[i].n, 0)) return -1; }
    unsigned char* pins[16]; for (i = 0; i < k && i < 16; i++) pins[i] = o[i].pin;
    if (sm11_fence()) return -1;
    for (i = 0; i < k; i++) if (pins[i]) memcpy(o[i].dst, pins[i], o[i].n);
    return 0;
}
static int sm11_dtoh_wait(void* dst, CUdeviceptr src, size_t n) { Sm11Out o = {dst, src, n, 0}; return sm11_dtoh_many(&o, 1); }

static char* load_ptx(void) {
    const char* candidates[3];
    int i;
    candidates[0] = getenv("SM11_PTX");
    candidates[1] = "kernels.ptx";
    candidates[2] = "gpu-legacy/kernels.ptx";
    for (i = 0; i < 3; i++) {
        const char* p = candidates[i];
        FILE* f;
        long n;
        char* buf;
        if (!p) continue;
        f = fopen(p, "rb"); if (!f) continue;
        fseek(f, 0, SEEK_END); n = ftell(f); fseek(f, 0, SEEK_SET);
        buf = (char*)malloc((size_t)n + 1); if (!buf) { fclose(f); return NULL; }
        if (fread(buf, 1, (size_t)n, f) != (size_t)n) { free(buf); fclose(f); return NULL; }
        buf[n] = 0; fclose(f);
        fprintf(stderr, "sm11: loaded PTX %s (%ld bytes)\n", p, n);
        return buf;
    }
    fprintf(stderr, "sm11: kernels.ptx not found (set SM11_PTX)\n");
    return NULL;
}

#define LOAD(n, s) do { *(FARPROC*)&p_##n = GetProcAddress(h, s); if (!p_##n) { fprintf(stderr, "sm11: missing %s\n", s); return -1; } } while (0)
#define CK(e) do { CUresult _r = (e); if (_r) { fprintf(stderr, "sm11: %s -> %d\n", #e, _r); return -1; } } while (0)

static CUfunction f_matvec, f_rmsnorm, f_add, f_silu, f_rope, f_copy, f_ascores, f_softmax, f_avalue, f_attn_fused, f_q4, f_q8, f_batch;
static CUdeviceptr g_pool_jobs = 0, g_pool_x[8], g_pool_y[8], g_pool_w[8];
static size_t g_pool_xsz[8], g_pool_ysz[8], g_pool_wsz[8];
static CUdeviceptr g_mv_dx = 0, g_mv_dy = 0; static size_t g_mv_dxsz = 0, g_mv_dysz = 0;
static CUdeviceptr g_q_dw = 0; static size_t g_q_dwsz = 0; static const void* g_q_host = 0; static int g_q_kind = 0;
static const char* g_hbase; static size_t g_nbytes, g_resident;
static CUdeviceptr g_dbase, g_stage; static size_t g_stage_bytes;
static int g_ready;

static Sm11Config g_cfg;
static CUdeviceptr d_x, d_xb, d_xb2, d_hb, d_hb2, d_q, d_att, d_logits, d_kc, d_vc, d_cos, d_sin, d_scores;
static const float *h_tok, *h_rms_att, *h_rms_ffn, *h_wq, *h_wk, *h_wv, *h_wo, *h_w1, *h_w2, *h_w3, *h_rms_f, *h_wcls;

static CUdeviceptr dptr(const float* h) {
    size_t off = (const char*)h - g_hbase;
    if (off + 4 <= g_resident) return g_dbase + off;
    return 0;
}

static CUmodule g_sm11_mod;
static int launch(CUfunction f, unsigned gx, unsigned bx, void** args) {
    return p_cuLaunchKernel(f, gx, 1, 1, bx, 1, 1, 0, 0, args, 0);
}

static int matvec_d(CUdeviceptr dy, CUdeviceptr dx, const float* hw, int n, int d) {
    size_t bytes = (size_t)n * d * 4, off = (const char*)hw - g_hbase;
    CUdeviceptr dW;
    if (off + bytes <= g_resident) {
        dW = g_dbase + off;
        unsigned un = (unsigned)n, ud = (unsigned)d;
        void* args[] = {&dy, &dx, &dW, &un, &ud};
        CK(launch(f_matvec, ud, 128, args));
        return 0;
    }
    size_t rowb = (size_t)n * 4;
    int rows = (int)(g_stage_bytes / rowb); if (rows < 1) return -1;
    unsigned un = (unsigned)n;
    for (int r0 = 0; r0 < d; r0 += rows) {
        int nr = d - r0 < rows ? d - r0 : rows; unsigned unr = (unsigned)nr;
        CUdeviceptr dy0 = dy + (CUdeviceptr)r0 * 4;
        CK(p_cuMemcpyHtoD(g_stage, hw + (size_t)r0 * n, rowb * nr));
        void* args[] = {&dy0, &dx, &g_stage, &un, &unr};
        CK(launch(f_matvec, unr, 128, args));
    }
    return 0;
}

int sm11_register(const void* base, size_t nbytes) {
    HMODULE h = LoadLibraryA("nvcuda.dll");
    if (!h) { fprintf(stderr, "sm11: nvcuda.dll not found\n"); return -1; }
    LOAD(cuInit, "cuInit"); LOAD(cuDeviceGet, "cuDeviceGet"); LOAD(cuDeviceGetName, "cuDeviceGetName");
    LOAD(cuDeviceComputeCapability, "cuDeviceComputeCapability"); LOAD(cuCtxCreate, "cuCtxCreate_v2");
    LOAD(cuModuleLoadDataEx, "cuModuleLoadDataEx"); LOAD(cuModuleGetFunction, "cuModuleGetFunction");
    LOAD(cuMemAlloc, "cuMemAlloc_v2"); LOAD(cuMemFree, "cuMemFree_v2"); LOAD(cuMemGetInfo, "cuMemGetInfo_v2");
    LOAD(cuMemcpyHtoD, "cuMemcpyHtoD_v2"); LOAD(cuMemcpyDtoH, "cuMemcpyDtoH_v2");
    LOAD(cuMemcpyDtoD, "cuMemcpyDtoD_v2"); LOAD(cuLaunchKernel, "cuLaunchKernel"); LOAD(cuCtxSynchronize, "cuCtxSynchronize"); async_init(h);
    CUdevice dev; CUcontext ctx; CUmodule mod; char name[128]; int ma=0, mi=0; size_t fr=0, tot=0;
    CK(p_cuInit(0)); CK(p_cuDeviceGet(&dev, 0)); CK(p_cuDeviceGetName(name, sizeof name, dev));
    CK(p_cuDeviceComputeCapability(&ma, &mi, dev)); CK(p_cuCtxCreate(&ctx, getenv("SM11_CTX_FLAGS") ? (unsigned)atoi(getenv("SM11_CTX_FLAGS")) : 4u /*SCHED_BLOCKING_SYNC*/, dev));
        char* ptx = load_ptx(); if (!ptx) return -1;
    char log[8192] = {0}; int opts[2] = {5, 6}; void* vals[2] = {log, (void*)(size_t)sizeof log};
    CUresult r = p_cuModuleLoadDataEx(&mod, ptx, 2, opts, vals);
    g_sm11_mod = mod;
    free(ptx);
    if (r) { fprintf(stderr, "sm11: PTX JIT failed %d: %s\n", r, log); return -1; }
    CK(p_cuModuleGetFunction(&f_matvec, mod, "k_matvec"));
    CK(p_cuModuleGetFunction(&f_rmsnorm, mod, "k_rmsnorm"));
    CK(p_cuModuleGetFunction(&f_add, mod, "k_add"));
    CK(p_cuModuleGetFunction(&f_silu, mod, "k_silu_mul"));
    CK(p_cuModuleGetFunction(&f_rope, mod, "k_rope"));
    CK(p_cuModuleGetFunction(&f_copy, mod, "k_copy"));
    CK(p_cuModuleGetFunction(&f_ascores, mod, "k_attn_scores"));
    CK(p_cuModuleGetFunction(&f_softmax, mod, "k_softmax"));
    CK(p_cuModuleGetFunction(&f_avalue, mod, "k_attn_value"));
    if (p_cuModuleGetFunction(&f_attn_fused, mod, "k_attn_fused") != 0) { fprintf(stderr, "sm11: k_attn_fused missing, using split attn\n"); f_attn_fused = 0; }
    if (p_cuModuleGetFunction(&f_q4, mod, "k_q4_matvec") != 0) f_q4 = 0;
    if (p_cuModuleGetFunction(&f_q8, mod, "k_q8_matvec") != 0) f_q8 = 0;
    if (p_cuModuleGetFunction(&f_batch, mod, "k_matvec_batch") != 0) f_batch = 0;
    CK(p_cuMemGetInfo(&fr, &tot));
    fprintf(stderr, "sm11: %s cc%d.%d vram free %u/%u MiB, weights %u MiB\n", name, ma, mi,
            (unsigned)(fr>>20), (unsigned)(tot>>20), (unsigned)(nbytes>>20));
    g_stage_bytes = 4u << 20;
    /* Prefer full residency for always-active models. Soften leave when the blob fits. */
    size_t leave = g_stage_bytes + (8u << 20);
    if (nbytes + leave <= fr) leave = g_stage_bytes + (4u << 20);
    size_t budget = fr > leave ? fr - leave : (fr > (4u<<20) ? fr - (4u<<20) : 0);
    const char* cap = getenv("SM11_RESIDENT_MIB");
    if (cap) { size_t c = (size_t)atoi(cap) << 20; if (c < budget) budget = c; }
    g_resident = nbytes < budget ? nbytes : budget;
    if (g_resident < nbytes)
        fprintf(stderr, "sm11: WARN only %u/%u MiB resident (freeVRAM %u); tok/s will drop.\n",
                (unsigned)(g_resident>>20), (unsigned)(nbytes>>20), (unsigned)(fr>>20));
    CK(p_cuMemAlloc(&g_stage, g_stage_bytes));
    if (g_resident) { CK(p_cuMemAlloc(&g_dbase, g_resident)); CK(p_cuMemcpyHtoD(g_dbase, base, g_resident)); }
    g_hbase = (const char*)base; g_nbytes = nbytes; g_ready = 1;
    fprintf(stderr, "sm11: resident %u MiB / %u MiB weights (role: always-active)\n",
            (unsigned)(g_resident>>20), (unsigned)(nbytes>>20));
    return 0;
}

int sm11_matmul(float* xout, const float* x, const float* w, int n, int d) {
    if (!g_ready) return -1;
    size_t xs = (size_t)n * 4, ys = (size_t)d * 4;
    if (xs > g_mv_dxsz) { if (g_mv_dx) p_cuMemFree(g_mv_dx); CK(p_cuMemAlloc(&g_mv_dx, xs)); g_mv_dxsz = xs; }
    if (ys > g_mv_dysz) { if (g_mv_dy) p_cuMemFree(g_mv_dy); CK(p_cuMemAlloc(&g_mv_dy, ys)); g_mv_dysz = ys; }
    CK(sm11_htod(g_mv_dx, x, xs));
    if (matvec_d(g_mv_dy, g_mv_dx, w, n, d)) return -1;
    CK(sm11_dtoh_wait(xout, g_mv_dy, ys));
    return 0;
}

int sm11_init(const Sm11Config* cfg,
              float* token_embedding_table, float* rms_att_weight, float* rms_ffn_weight,
              float* wq, float* wk, float* wv, float* wo,
              float* w1, float* w2, float* w3, float* rms_final_weight, float* wcls) {
    if (!g_ready) return -1;
    g_cfg = *cfg;
    h_tok = token_embedding_table; h_rms_att = rms_att_weight; h_rms_ffn = rms_ffn_weight;
    h_wq = wq; h_wk = wk; h_wv = wv; h_wo = wo; h_w1 = w1; h_w2 = w2; h_w3 = w3;
    h_rms_f = rms_final_weight; h_wcls = wcls;
    int dim = cfg->dim, hd = cfg->hidden_dim, kv = (dim * cfg->n_kv_heads) / cfg->n_heads;
    size_t kvbytes = (size_t)cfg->n_layers * cfg->seq_len * kv * 4;
    CK(p_cuMemAlloc(&d_x, dim*4)); CK(p_cuMemAlloc(&d_xb, dim*4)); CK(p_cuMemAlloc(&d_xb2, dim*4));
    CK(p_cuMemAlloc(&d_hb, hd*4)); CK(p_cuMemAlloc(&d_hb2, hd*4)); CK(p_cuMemAlloc(&d_q, dim*4));
    CK(p_cuMemAlloc(&d_att, (size_t)cfg->n_heads * cfg->seq_len * 4));
    CK(p_cuMemAlloc(&d_logits, (size_t)cfg->vocab_size * 4));
    CK(p_cuMemAlloc(&d_kc, kvbytes)); CK(p_cuMemAlloc(&d_vc, kvbytes));
    CK(p_cuMemAlloc(&d_cos, (dim/cfg->n_heads/2)*4)); CK(p_cuMemAlloc(&d_sin, (dim/cfg->n_heads/2)*4));
    CK(p_cuMemAlloc(&d_scores, (size_t)cfg->seq_len * 4));
    fprintf(stderr, "sm11: on-device forward ready (kv %u MiB, dim=%d layers=%d)\n",
            (unsigned)((kvbytes*2)>>20), dim, cfg->n_layers);
    return 0;
}

void sm11_reset_kv(void) {}

static int rmsnorm_d(CUdeviceptr out, CUdeviceptr x, const float* hw, int n) {
    CUdeviceptr dw = dptr(hw);
    CUdeviceptr tmp = 0;
    if (!dw) { CK(p_cuMemAlloc(&tmp, (size_t)n*4)); CK(p_cuMemcpyHtoD(tmp, hw, (size_t)n*4)); dw = tmp; }
    unsigned un = (unsigned)n; void* args[] = {&out, &x, &dw, &un};
    CK(launch(f_rmsnorm, 1, 128, args));
    if (tmp) p_cuMemFree(tmp);
    return 0;
}
static int add_d(CUdeviceptr x, CUdeviceptr y, int n) {
    unsigned un = (unsigned)n, grid = (n + 127) / 128;
    void* args[] = {&x, &y, &un}; CK(launch(f_add, grid, 128, args)); return 0;
}
static int silu_d(CUdeviceptr hb, CUdeviceptr hb2, int n) {
    unsigned un = (unsigned)n, grid = (n + 127) / 128;
    void* args[] = {&hb, &hb2, &un}; CK(launch(f_silu, grid, 128, args)); return 0;
}
static int copy_d(CUdeviceptr dst, CUdeviceptr src, int n) {
    unsigned un = (unsigned)n, grid = (n + 127) / 128;
    void* args[] = {&dst, &src, &un}; CK(launch(f_copy, grid, 128, args)); return 0;
}

int sm11_forward(int token, int pos, float* logits_out) {
    if (!g_ready) return -1;
    Sm11Config* p = &g_cfg;
    int dim = p->dim, hd = p->hidden_dim, nh = p->n_heads, nkv = p->n_kv_heads;
    int kv_dim = (dim * nkv) / nh, kv_mul = nh / nkv, hs = dim / nh;
    const float* erow = h_tok + (size_t)token * dim;
    CUdeviceptr de = dptr(erow);
    if (de) { CK(copy_d(d_x, de, dim)); }
    else { CK(sm11_htod(d_x, erow, (size_t)dim * 4)); }

    int h2 = hs / 2;
    float *cosb = (float*)malloc((size_t)h2 * 4), *sinb = (float*)malloc((size_t)h2 * 4);
    for (int i = 0; i < h2; i++) {
        float freq = 1.0f / powf(10000.0f, (2.0f * i) / (float)hs);
        float val = pos * freq; cosb[i] = cosf(val); sinb[i] = sinf(val);
    }
    CK(sm11_htod(d_cos, cosb, (size_t)h2 * 4)); CK(sm11_htod(d_sin, sinb, (size_t)h2 * 4));
    free(cosb); free(sinb);

    for (int l = 0; l < p->n_layers; l++) {
        if (rmsnorm_d(d_xb, d_x, h_rms_att + (size_t)l * dim, dim)) return -1;
        CUdeviceptr d_k = d_kc + (CUdeviceptr)((size_t)l * p->seq_len * kv_dim + (size_t)pos * kv_dim) * 4;
        CUdeviceptr d_v = d_vc + (CUdeviceptr)((size_t)l * p->seq_len * kv_dim + (size_t)pos * kv_dim) * 4;
        if (matvec_d(d_q, d_xb, h_wq + (size_t)l * dim * dim, dim, dim)) return -1;
        if (matvec_d(d_k, d_xb, h_wk + (size_t)l * dim * kv_dim, dim, kv_dim)) return -1;
        if (matvec_d(d_v, d_xb, h_wv + (size_t)l * dim * kv_dim, dim, kv_dim)) return -1;
        unsigned udim=dim, uhs=hs, ukv=kv_dim;
        void* rargs[] = {&d_q, &d_k, &d_cos, &d_sin, &udim, &uhs, &ukv};
        CK(launch(f_rope, (dim/2 + 127) / 128, 128, rargs));

        CUdeviceptr layer_k = d_kc + (CUdeviceptr)((size_t)l * p->seq_len * kv_dim) * 4;
        CUdeviceptr layer_v = d_vc + (CUdeviceptr)((size_t)l * p->seq_len * kv_dim) * 4;
        unsigned uT = (unsigned)(pos + 1), uhs2 = (unsigned)hs, ukvd = (unsigned)kv_dim;
        for (int h = 0; h < nh; h++) {
            CUdeviceptr qh = d_q + (CUdeviceptr)(h * hs) * 4;
            CUdeviceptr kh = layer_k + (CUdeviceptr)((h / kv_mul) * hs) * 4;
            CUdeviceptr vh = layer_v + (CUdeviceptr)((h / kv_mul) * hs) * 4;
            CUdeviceptr xb = d_xb + (CUdeviceptr)(h * hs) * 4;
            if (f_attn_fused) {
                void* fargs[] = {&qh, &kh, &vh, &xb, &uhs2, &uT, &ukvd};
                CK(launch(f_attn_fused, 1, 128, fargs));
            } else {
                void* sargs[] = {&qh, &kh, &d_scores, &uhs2, &uT, &ukvd};
                CK(launch(f_ascores, 1, 128, sargs));
                void* soargs[] = {&d_scores, &uT};
                CK(launch(f_softmax, 1, 128, soargs));
                void* vargs[] = {&d_scores, &vh, &xb, &uhs2, &uT, &ukvd};
                CK(launch(f_avalue, 1, 128, vargs));
            }
        }
        if (matvec_d(d_xb2, d_xb, h_wo + (size_t)l * dim * dim, dim, dim)) return -1;
        if (add_d(d_x, d_xb2, dim)) return -1;
        if (rmsnorm_d(d_xb, d_x, h_rms_ffn + (size_t)l * dim, dim)) return -1;
        if (matvec_d(d_hb, d_xb, h_w1 + (size_t)l * dim * hd, dim, hd)) return -1;
        if (matvec_d(d_hb2, d_xb, h_w3 + (size_t)l * dim * hd, dim, hd)) return -1;
        if (silu_d(d_hb, d_hb2, hd)) return -1;
        if (matvec_d(d_xb, d_hb, h_w2 + (size_t)l * dim * hd, hd, dim)) return -1;
        if (add_d(d_x, d_xb, dim)) return -1;
    }
    if (rmsnorm_d(d_x, d_x, h_rms_f, dim)) return -1;
    /* Vocab projection is 32k rows — WDDM launch overhead dominates on sm_11. Default: CPU cls. */
    if (!getenv("SM11_GPU_CLS") || !atoi(getenv("SM11_GPU_CLS"))) {
        float* xh = (float*)malloc((size_t)dim * 4);
        CK(sm11_dtoh_wait(xh, d_x, (size_t)dim * 4));
        const float* w = h_wcls;
        #pragma omp parallel for
        for (int i = 0; i < p->vocab_size; i++) {
            float v = 0.0f; const float* wr = w + (size_t)i * dim;
            for (int j = 0; j < dim; j++) v += wr[j] * xh[j];
            logits_out[i] = v;
        }
        free(xh);
        return 0;
    }
    if (matvec_d(d_logits, d_x, h_wcls, dim, p->vocab_size)) return -1;
    CK(sm11_dtoh_wait(logits_out, d_logits, (size_t)p->vocab_size * 4));
    return 0;
}


int sm11_q4_matmul(float* xout, const float* x, const void* w_q4, int n, int d) {
    if (!g_ready || !f_q4 || (n & 31)) return -1;
    size_t xs=(size_t)n*4, ys=(size_t)d*4, wbytes=(size_t)(n/32)*18*(size_t)d;
    if (xs > g_mv_dxsz) { if (g_mv_dx) p_cuMemFree(g_mv_dx); CK(p_cuMemAlloc(&g_mv_dx, xs)); g_mv_dxsz=xs; }
    if (ys > g_mv_dysz) { if (g_mv_dy) p_cuMemFree(g_mv_dy); CK(p_cuMemAlloc(&g_mv_dy, ys)); g_mv_dysz=ys; }
    if (w_q4 != g_q_host || g_q_kind != 4 || wbytes > g_q_dwsz) {
        if (wbytes > g_q_dwsz) { if (g_q_dw) p_cuMemFree(g_q_dw); CK(p_cuMemAlloc(&g_q_dw, wbytes)); g_q_dwsz=wbytes; }
        CK(p_cuMemcpyHtoD(g_q_dw, w_q4, wbytes));
        g_q_host = w_q4; g_q_kind = 4;
    }
    CK(sm11_htod(g_mv_dx, x, xs));
    unsigned un=(unsigned)n, ud=(unsigned)d;
    void* args[] = {&g_mv_dy, &g_mv_dx, &g_q_dw, &un, &ud};
    CK(launch(f_q4, ud, 64, args));
    CK(sm11_dtoh_wait(xout, g_mv_dy, ys));
    return 0;
}

int sm11_q8_matmul(float* xout, const float* x, const void* w_q8, int n, int d) {
    if (!g_ready || !f_q8 || (n & 31)) return -1;
    size_t xs=(size_t)n*4, ys=(size_t)d*4, wbytes=(size_t)(n/32)*34*(size_t)d;
    if (xs > g_mv_dxsz) { if (g_mv_dx) p_cuMemFree(g_mv_dx); CK(p_cuMemAlloc(&g_mv_dx, xs)); g_mv_dxsz=xs; }
    if (ys > g_mv_dysz) { if (g_mv_dy) p_cuMemFree(g_mv_dy); CK(p_cuMemAlloc(&g_mv_dy, ys)); g_mv_dysz=ys; }
    if (w_q8 != g_q_host || g_q_kind != 8 || wbytes > g_q_dwsz) {
        if (wbytes > g_q_dwsz) { if (g_q_dw) p_cuMemFree(g_q_dw); CK(p_cuMemAlloc(&g_q_dw, wbytes)); g_q_dwsz=wbytes; }
        CK(p_cuMemcpyHtoD(g_q_dw, w_q8, wbytes));
        g_q_host = w_q8; g_q_kind = 8;
    }
    CK(sm11_htod(g_mv_dx, x, xs));
    unsigned un=(unsigned)n, ud=(unsigned)d;
    void* args[] = {&g_mv_dy, &g_mv_dx, &g_q_dw, &un, &ud};
    CK(launch(f_q8, ud, 64, args));
    CK(sm11_dtoh_wait(xout, g_mv_dy, ys));
    return 0;
}

int sm11_matvec_batch(const Sm11Job* jobs, int njobs) {
    if (!g_ready || njobs < 1 || njobs > 8) return -1;
    /* Pipelined matvec_d (uses resident W when registered) + one sync. */
    for (int i = 0; i < njobs; i++) {
        size_t xs = (size_t)jobs[i].n * 4, ys = (size_t)jobs[i].d * 4;
        if (xs > g_pool_xsz[i]) {
            if (g_pool_x[i]) p_cuMemFree(g_pool_x[i]);
            CK(p_cuMemAlloc(&g_pool_x[i], xs)); g_pool_xsz[i] = xs;
        }
        if (ys > g_pool_ysz[i]) {
            if (g_pool_y[i]) p_cuMemFree(g_pool_y[i]);
            CK(p_cuMemAlloc(&g_pool_y[i], ys)); g_pool_ysz[i] = ys;
        }
        CUdeviceptr dx;
        if (i > 0 && jobs[i].x == jobs[0].x && jobs[i].n == jobs[0].n) {
            dx = g_pool_x[0];
        } else {
            CK(sm11_htod(g_pool_x[i], jobs[i].x, xs));
            dx = g_pool_x[i];
        }
        if (matvec_d(g_pool_y[i], dx, jobs[i].w, jobs[i].n, jobs[i].d)) return -1;
    }
    { Sm11Out o[8]; for (int i = 0; i < njobs; i++) { o[i].dst = jobs[i].y; o[i].src = g_pool_y[i]; o[i].n = (size_t)jobs[i].d * 4; o[i].pin = 0; }
      CK(sm11_dtoh_many(o, njobs)); }
    return 0;
}


/* ---- ggml weight cache: host ptr -> resident device copy, under a VRAM safety margin ---- */
#define SM11_WC_MAX 512
static struct { const void* h; CUdeviceptr d; size_t n; } g_wc[SM11_WC_MAX];
static int g_wc_n = 0; static size_t g_wc_bytes = 0; static int g_wc_full = 0;
static size_t wc_margin(void) {
    const char* m = getenv("SM11_VRAM_MARGIN_MIB");
    return (size_t)(m ? atoi(m) : 16) << 20;
}
static CUdeviceptr wc_get(const void* h, size_t n) {
    for (int i = 0; i < g_wc_n; i++) if (g_wc[i].h == h && g_wc[i].n == n) return g_wc[i].d;
    if (g_wc_full || g_wc_n >= SM11_WC_MAX) return 0;
    size_t fr = 0, tot = 0;
    if (p_cuMemGetInfo(&fr, &tot) || fr < n + wc_margin()) { g_wc_full = 1;
        fprintf(stderr, "sm11: weight cache full at %u MiB (free %u MiB, margin %u MiB); rest stays on CPU\n",
                (unsigned)(g_wc_bytes>>20), (unsigned)(fr>>20), (unsigned)(wc_margin()>>20));
        return 0; }
    CUdeviceptr d;
    if (p_cuMemAlloc(&d, n)) { g_wc_full = 1; return 0; }
    if (p_cuMemcpyHtoD(d, h, n)) { p_cuMemFree(d); return 0; }
    g_wc[g_wc_n].h = h; g_wc[g_wc_n].d = d; g_wc[g_wc_n].n = n; g_wc_n++; g_wc_bytes += n;
    return d;
}
size_t sm11_wcache_bytes(void) { return g_wc_bytes; }
/* kind: 0=F32, 4=Q4_0, 8=Q8_0. Returns 0 on GPU success, -1 => caller does CPU. */
int sm11_wmatvec(int kind, float* y, const float* x, const void* w, int n, int d) {
    if (!g_ready) return -1;
    CUfunction f; size_t wb;
    if (kind == 0) { f = f_matvec; wb = (size_t)n * d * 4; }
    else if (kind == 4) { if (!f_q4 || (n & 31)) return -1; f = f_q4; wb = (size_t)(n/32)*18*d; }
    else if (kind == 8) { if (!f_q8 || (n & 31)) return -1; f = f_q8; wb = (size_t)(n/32)*34*d; }
    else return -1;
    if (kind != 0 && n > 1536) return -1;          /* smem x cache holds 1536 floats */
    CUdeviceptr dw = wc_get(w, wb); if (!dw) return -1;
    size_t xs = (size_t)n*4, ys = (size_t)d*4;
    if (xs > g_mv_dxsz) { if (g_mv_dx) p_cuMemFree(g_mv_dx); CK(p_cuMemAlloc(&g_mv_dx, xs)); g_mv_dxsz = xs; }
    if (ys > g_mv_dysz) { if (g_mv_dy) p_cuMemFree(g_mv_dy); CK(p_cuMemAlloc(&g_mv_dy, ys)); g_mv_dysz = ys; }
    CK(sm11_htod(g_mv_dx, x, xs));
    unsigned un = (unsigned)n, ud = (unsigned)d;
    void* args[] = {&g_mv_dy, &g_mv_dx, &dw, &un, &ud};
    unsigned grid = ud;
    if (kind) { const char* g = getenv("SM11_QGRID"); unsigned gq = g ? (unsigned)atoi(g) : 32; if (gq && gq < grid) grid = gq; }
    CK(launch(f, grid, kind ? 64 : 128, args));
    CK(sm11_dtoh_wait(y, g_mv_dy, ys));   /* async D2H + event poll */
    return 0;
}
