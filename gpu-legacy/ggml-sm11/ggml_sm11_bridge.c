#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Declared in sm11_shim.h — keep C linkage for ggml-cpu.c */
#include "../../sm11_shim.h"

static int alive = 0;
static const void * registered_base = 0;
static size_t registered_bytes = 0;

int ggml_sm11_ensure(const void * base, size_t nbytes) {
    if (alive && registered_base == base && registered_bytes == nbytes) return 0;
    if (sm11_register(base, nbytes) != 0) return -1;
    registered_base = base; registered_bytes = nbytes; alive = 1;
    return 0;
}

int ggml_sm11_try_mul_mat(float * y, const float * x, const float * w, int n, int d) {
    if (!getenv("SM11_OFFLOAD") || !atoi(getenv("SM11_OFFLOAD"))) return -1;
    if (!alive) {
        /* Best-effort: cannot register unknown blob; require ggml_sm11_ensure first. */
        return -1;
    }
    /* Weight pointer must lie inside registered blob — sm11_matmul checks that. */
    return sm11_matmul(y, x, w, n, d);
}
