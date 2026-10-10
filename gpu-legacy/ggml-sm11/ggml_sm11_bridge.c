#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sm11_shim.h"
static int alive = 0;
int ggml_sm11_ensure(const void * base, size_t nbytes) {
    if (alive) return 0;
    if (sm11_register(base ? base : (const void*)1, nbytes ? nbytes : 1) != 0) return -1;
    alive = 1; return 0;
}
int ggml_sm11_try_mul_mat(float * y, const float * x, const float * w, int n, int d) {
    if (!getenv("SM11_OFFLOAD") || !atoi(getenv("SM11_OFFLOAD"))) return -1;
    if ((long long)n * d < 50000) return -1;
    if (!alive && ggml_sm11_ensure(NULL, 0) != 0) return -1;
    return sm11_matmul(y, x, w, n, d);
}
