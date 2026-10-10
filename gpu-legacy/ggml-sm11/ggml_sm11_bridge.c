#include <stdio.h>
#include <stdlib.h>
#include "sm11_shim.h"
static int state = 0; /* 0 untried, 1 alive, -1 failed */
static int on(void) {
    if (state) return state > 0;
    const char* e = getenv("SM11_OFFLOAD");
    if (!e || !atoi(e) || sm11_register(NULL, 0) != 0) { state = -1; return 0; }
    state = 1; return 1;
}
/* kind 0=F32 4=Q4_0 8=Q8_0 */
int ggml_sm11_try_mul_mat_k(int kind, float * y, const float * x, const void * w, int n, int d) {
    if (!on()) return -1;
    if ((long long)n * d < 50000) return -1;
    return sm11_wmatvec(kind, y, x, w, n, d);
}
int ggml_sm11_try_mul_mat(float * y, const float * x, const float * w, int n, int d) {
    return ggml_sm11_try_mul_mat_k(0, y, x, w, n, d);
}
