// ggml-sm11: thin MUL_MAT offload through sm11_shim C ABI.
// Built against llama.cpp headers; link with sm11_shim.c and nvcuda (runtime LoadLibrary).
// This is intentionally small: buffer type = host; compute = intercept mul_mat.
#include "ggml-sm11.h"
#include "ggml.h"
#include "ggml-backend.h"
#include "ggml-backend-impl.h"
#include "ggml-impl.h"
#include <cstring>
#include <cstdio>
#include <vector>

extern "C" {
#include "../sm11_shim.h"
}

static bool sm11_alive = false;

int ggml_backend_sm11_probe(char * desc, int n) {
    // Soft probe: try register empty? Just report presence of nvcuda via LoadLibrary in sm11_register.
    if (desc && n > 0) snprintf(desc, n, "sm11 (CUDA driver, GeForce 8/9)");
    return 1;
}

const char * ggml_backend_sm11_name(void) { return "SM11"; }

// We expose a "CPU-like" backend that overrides graph compute for MUL_MAT nodes.
// Simpler integration path used by familia: call ggml_sm11_compute_forward_mul_mat from a
// custom ggml_backend_graph_compute. For llama.cpp in-tree, register via ggml_backend_register.

static struct ggml_backend_sm11_context {
    bool ok;
} g_ctx;

// Public helper used by our patched llama.cpp graph compute:
extern "C" int ggml_sm11_try_mul_mat(float * y, const float * x, const float * w, int n, int d) {
    if (!sm11_alive) return -1;
    return sm11_matmul(y, x, w, n, d);
}

extern "C" int ggml_sm11_ensure(const void * weight_base, size_t nbytes) {
    if (sm11_alive) return 0;
    if (sm11_register(weight_base, nbytes) != 0) return -1;
    sm11_alive = true;
    return 0;
}

// Minimal backend object so llama.cpp can list it.
struct ggml_backend_sm11 {
    ggml_backend_sm11_context ctx;
};

static const char * backend_name(ggml_backend_t backend) {
    return "SM11";
}

static void backend_free(ggml_backend_t backend) {
    delete (ggml_backend_sm11 *)backend->context;
    delete backend;
}

static ggml_status backend_graph_compute(ggml_backend_t backend, ggml_cgraph * cgraph) {
    // Fallback: not a full backend yet — return error so caller uses CPU.
    // Real MUL_MAT offload is via ggml_sm11_try_mul_mat from a CPU backend hook.
    (void)backend; (void)cgraph;
    return GGML_STATUS_FAILED;
}

static struct ggml_backend_i sm11_backend_i = {
    /* .get_name                = */ backend_name,
    /* .free                    = */ backend_free,
    /* .set_tensor_async        = */ NULL,
    /* .get_tensor_async        = */ NULL,
    /* .cpy_tensor_async        = */ NULL,
    /* .synchronize             = */ NULL,
    /* .graph_plan_create       = */ NULL,
    /* .graph_plan_free         = */ NULL,
    /* .graph_plan_update       = */ NULL,
    /* .graph_plan_compute      = */ NULL,
    /* .graph_compute           = */ backend_graph_compute,
    /* .event_record            = */ NULL,
    /* .event_wait              = */ NULL,
};

ggml_backend_t ggml_backend_sm11_init(void) {
    auto * ctx = new ggml_backend_sm11_context{false};
    ggml_backend_t backend = new ggml_backend{
        /* .guid    = */ {},
        /* .iface   = */ sm11_backend_i,
        /* .device  = */ nullptr,
        /* .context = */ ctx,
    };
    return backend;
}
