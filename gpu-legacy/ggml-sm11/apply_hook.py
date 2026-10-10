"""Patch E:/temp/llama.cpp/ggml/src/ggml-cpu/ggml-cpu.c to call sm11 for F32 gemv."""
import sys
path = sys.argv[1]
src = open(path, encoding='utf-8', errors='replace').read()
needle = 'void ggml_compute_forward_mul_mat(\n        const struct ggml_compute_params * params,\n              struct ggml_tensor * dst) {\n\n    const struct ggml_tensor * src0 = dst->src[0];\n    const struct ggml_tensor * src1 = dst->src[1];'
hook = needle + '''

#if defined(GGML_USE_SM11)
    if (!params->use_ref && src0->type == GGML_TYPE_F32 && src1->type == GGML_TYPE_F32
        && ggml_is_contiguous(src0) && ggml_is_contiguous(src1)
        && src1->ne[1] == 1 && src1->ne[2] == 1 && src1->ne[3] == 1
        && params->ith == 0) {
        extern int ggml_sm11_try_mul_mat(float *, const float *, const float *, int, int);
        if (ggml_sm11_try_mul_mat((float *)dst->data, (const float *)src1->data,
                                  (const float *)src0->data, (int)src0->ne[0], (int)src0->ne[1]) == 0) {
            return;
        }
    }
#endif
'''
if 'GGML_USE_SM11' in src:
    print('already patched')
else:
    if needle not in src:
        sys.exit('needle not found')
    src = src.replace(needle, hook, 1)
    open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched', path)
