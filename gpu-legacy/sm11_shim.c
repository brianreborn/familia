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

static const char* PTX =
".version 4.1\n"
".target sm_11\n"
".address_size 64\n"
"\n"
".visible .entry k_matvec(.param .u64 py, .param .u64 px, .param .u64 pw, .param .u32 pn, .param .u32 pd)\n"
"{\n"
"  .reg .u32 %r<16>;\n"
"  .reg .u64 %rd<16>;\n"
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
"}\n"
"\n"
".visible .entry k_rmsnorm(.param .u64 pout, .param .u64 px, .param .u64 pw, .param .u32 pn)\n"
"{\n"
"  .reg .u32 %r<12>;\n"
"  .reg .u64 %rd<14>;\n"
"  .reg .f32 %f<10>;\n"
"  .reg .pred %p<4>;\n"
"  .shared .align 4 .f32 sm[128];\n"
"\n"
"  ld.param.u64 %rd1, [pout];\n"
"  ld.param.u64 %rd2, [px];\n"
"  ld.param.u64 %rd3, [pw];\n"
"  ld.param.u32 %r1, [pn];\n"
"  mov.u32 %r4, %tid.x;\n"
"  mov.f32 %f1, 0f00000000;\n"
"  mov.u32 %r5, %r4;\n"
"SLOOP:\n"
"  setp.ge.u32 %p1, %r5, %r1;\n"
"  @%p1 bra SRED;\n"
"  mul.wide.u32 %rd5, %r5, 4;\n"
"  add.u64 %rd6, %rd2, %rd5;\n"
"  ld.global.f32 %f2, [%rd6];\n"
"  mad.f32 %f1, %f2, %f2, %f1;\n"
"  add.u32 %r5, %r5, 128;\n"
"  bra SLOOP;\n"
"SRED:\n"
"  mov.u64 %rd8, sm;\n"
"  mul.wide.u32 %rd9, %r4, 4;\n"
"  add.u64 %rd9, %rd8, %rd9;\n"
"  st.shared.f32 [%rd9], %f1;\n"
"  mov.u32 %r6, 64;\n"
"RLOOP:\n"
"  bar.sync 0;\n"
"  setp.ge.u32 %p2, %r4, %r6;\n"
"  @%p2 bra RSKIP;\n"
"  mul.wide.u32 %rd10, %r6, 4;\n"
"  add.u64 %rd10, %rd9, %rd10;\n"
"  ld.shared.f32 %f3, [%rd9];\n"
"  ld.shared.f32 %f4, [%rd10];\n"
"  add.f32 %f3, %f3, %f4;\n"
"  st.shared.f32 [%rd9], %f3;\n"
"RSKIP:\n"
"  shr.u32 %r6, %r6, 1;\n"
"  setp.ne.u32 %p3, %r6, 0;\n"
"  @%p3 bra RLOOP;\n"
"  ld.shared.f32 %f5, [%rd8];\n"
"  cvt.rn.f32.u32 %f6, %r1;\n"
"  div.approx.f32 %f5, %f5, %f6;\n"
"  add.f32 %f5, %f5, 0f3727c5ac;\n"
"  sqrt.approx.f32 %f5, %f5;\n"
"  rcp.approx.f32 %f5, %f5;\n"
"  bar.sync 0;\n"
"  mov.u32 %r5, %r4;\n"
"WLOOP:\n"
"  setp.ge.u32 %p1, %r5, %r1;\n"
"  @%p1 bra DONE;\n"
"  mul.wide.u32 %rd5, %r5, 4;\n"
"  add.u64 %rd6, %rd2, %rd5;\n"
"  add.u64 %rd7, %rd3, %rd5;\n"
"  add.u64 %rd4, %rd1, %rd5;\n"
"  ld.global.f32 %f2, [%rd6];\n"
"  ld.global.f32 %f7, [%rd7];\n"
"  mul.f32 %f2, %f2, %f5;\n"
"  mul.f32 %f2, %f2, %f7;\n"
"  st.global.f32 [%rd4], %f2;\n"
"  add.u32 %r5, %r5, 128;\n"
"  bra WLOOP;\n"
"DONE:\n"
"  exit;\n"
"}\n"
"\n"
".visible .entry k_add(.param .u64 px, .param .u64 py, .param .u32 pn)\n"
"{\n"
"  .reg .u32 %r<8>;\n"
"  .reg .u64 %rd<8>;\n"
"  .reg .f32 %f<4>;\n"
"  .reg .pred %p<2>;\n"
"  ld.param.u64 %rd1, [px];\n"
"  ld.param.u64 %rd2, [py];\n"
"  ld.param.u32 %r1, [pn];\n"
"  mov.u32 %r3, %ctaid.x;\n"
"  mov.u32 %r4, %ntid.x;\n"
"  mov.u32 %r5, %tid.x;\n"
"  mad.lo.u32 %r6, %r3, %r4, %r5;\n"
"  setp.ge.u32 %p1, %r6, %r1;\n"
"  @%p1 bra DONE;\n"
"  mul.wide.u32 %rd3, %r6, 4;\n"
"  add.u64 %rd4, %rd1, %rd3;\n"
"  add.u64 %rd5, %rd2, %rd3;\n"
"  ld.global.f32 %f1, [%rd4];\n"
"  ld.global.f32 %f2, [%rd5];\n"
"  add.f32 %f1, %f1, %f2;\n"
"  st.global.f32 [%rd4], %f1;\n"
"DONE:\n"
"  exit;\n"
"}\n"
"\n"
".visible .entry k_silu_mul(.param .u64 phb, .param .u64 phb2, .param .u32 pn)\n"
"{\n"
"  .reg .u32 %r<8>;\n"
"  .reg .u64 %rd<8>;\n"
"  .reg .f32 %f<8>;\n"
"  .reg .pred %p<2>;\n"
"  ld.param.u64 %rd1, [phb];\n"
"  ld.param.u64 %rd2, [phb2];\n"
"  ld.param.u32 %r1, [pn];\n"
"  mov.u32 %r3, %ctaid.x;\n"
"  mov.u32 %r4, %ntid.x;\n"
"  mov.u32 %r5, %tid.x;\n"
"  mad.lo.u32 %r6, %r3, %r4, %r5;\n"
"  setp.ge.u32 %p1, %r6, %r1;\n"
"  @%p1 bra DONE;\n"
"  mul.wide.u32 %rd3, %r6, 4;\n"
"  add.u64 %rd4, %rd1, %rd3;\n"
"  add.u64 %rd5, %rd2, %rd3;\n"
"  ld.global.f32 %f1, [%rd4];\n"
"  ld.global.f32 %f2, [%rd5];\n"
"  mul.f32 %f3, %f1, 0fbfb8aa3b;\n"
"  ex2.approx.f32 %f3, %f3;\n"
"  add.f32 %f3, %f3, 0f3f800000;\n"
"  rcp.approx.f32 %f3, %f3;\n"
"  mul.f32 %f1, %f1, %f3;\n"
"  mul.f32 %f1, %f1, %f2;\n"
"  st.global.f32 [%rd4], %f1;\n"
"DONE:\n"
"  exit;\n"
"}\n"
"\n"
".visible .entry k_rope(.param .u64 pq, .param .u64 pk, .param .u64 pcos, .param .u64 psin,\n"
"                       .param .u32 pdim, .param .u32 phs, .param .u32 pkv)\n"
"{\n"
"  .reg .u32 %r<14>;\n"
"  .reg .u64 %rd<14>;\n"
"  .reg .f32 %f<10>;\n"
"  .reg .pred %p<4>;\n"
"  ld.param.u64 %rd1, [pq];\n"
"  ld.param.u64 %rd2, [pk];\n"
"  ld.param.u64 %rd3, [pcos];\n"
"  ld.param.u64 %rd4, [psin];\n"
"  ld.param.u32 %r1, [pdim];\n"
"  ld.param.u32 %r2, [phs];\n"
"  ld.param.u32 %r3, [pkv];\n"
"  mov.u32 %r4, %ctaid.x;\n"
"  mov.u32 %r5, %ntid.x;\n"
"  mov.u32 %r6, %tid.x;\n"
"  mad.lo.u32 %r7, %r4, %r5, %r6;\n"
"  shl.b32 %r7, %r7, 1;\n"
"  setp.ge.u32 %p1, %r7, %r1;\n"
"  @%p1 bra DONE;\n"
"  rem.u32 %r8, %r7, %r2;\n"
"  shr.u32 %r8, %r8, 1;\n"
"  mul.wide.u32 %rd5, %r8, 4;\n"
"  add.u64 %rd6, %rd3, %rd5;\n"
"  add.u64 %rd7, %rd4, %rd5;\n"
"  ld.global.f32 %f1, [%rd6];\n"
"  ld.global.f32 %f2, [%rd7];\n"
"  mul.wide.u32 %rd8, %r7, 4;\n"
"  add.u64 %rd9, %rd1, %rd8;\n"
"  ld.global.f32 %f3, [%rd9];\n"
"  add.u64 %rd10, %rd9, 4;\n"
"  ld.global.f32 %f4, [%rd10];\n"
"  mul.f32 %f5, %f3, %f1;\n"
"  mul.f32 %f6, %f4, %f2;\n"
"  sub.f32 %f5, %f5, %f6;\n"
"  mul.f32 %f6, %f3, %f2;\n"
"  mul.f32 %f7, %f4, %f1;\n"
"  add.f32 %f6, %f6, %f7;\n"
"  st.global.f32 [%rd9], %f5;\n"
"  st.global.f32 [%rd10], %f6;\n"
"  setp.ge.u32 %p2, %r7, %r3;\n"
"  @%p2 bra DONE;\n"
"  add.u64 %rd9, %rd2, %rd8;\n"
"  ld.global.f32 %f3, [%rd9];\n"
"  add.u64 %rd10, %rd9, 4;\n"
"  ld.global.f32 %f4, [%rd10];\n"
"  mul.f32 %f5, %f3, %f1;\n"
"  mul.f32 %f6, %f4, %f2;\n"
"  sub.f32 %f5, %f5, %f6;\n"
"  mul.f32 %f6, %f3, %f2;\n"
"  mul.f32 %f7, %f4, %f1;\n"
"  add.f32 %f6, %f6, %f7;\n"
"  st.global.f32 [%rd9], %f5;\n"
"  st.global.f32 [%rd10], %f6;\n"
"DONE:\n"
"  exit;\n"
"}\n"
"\n"
".visible .entry k_copy(.param .u64 pdst, .param .u64 psrc, .param .u32 pn)\n"
"{\n"
"  .reg .u32 %r<8>;\n"
"  .reg .u64 %rd<8>;\n"
"  .reg .f32 %f<2>;\n"
"  .reg .pred %p<2>;\n"
"  ld.param.u64 %rd1, [pdst];\n"
"  ld.param.u64 %rd2, [psrc];\n"
"  ld.param.u32 %r1, [pn];\n"
"  mov.u32 %r3, %ctaid.x;\n"
"  mov.u32 %r4, %ntid.x;\n"
"  mov.u32 %r5, %tid.x;\n"
"  mad.lo.u32 %r6, %r3, %r4, %r5;\n"
"  setp.ge.u32 %p1, %r6, %r1;\n"
"  @%p1 bra DONE;\n"
"  mul.wide.u32 %rd3, %r6, 4;\n"
"  add.u64 %rd4, %rd1, %rd3;\n"
"  add.u64 %rd5, %rd2, %rd3;\n"
"  ld.global.f32 %f1, [%rd5];\n"
"  st.global.f32 [%rd4], %f1;\n"
"DONE:\n"
"  exit;\n"
"}\n"
"\n"
".visible .entry k_attn_scores(.param .u64 pq, .param .u64 pk, .param .u64 pscores,\n"
"                              .param .u32 phs, .param .u32 pT, .param .u32 pkvdim)\n"
"{\n"
"  .reg .u32 %r<14>;\n"
"  .reg .u64 %rd<12>;\n"
"  .reg .f32 %f<8>;\n"
"  .reg .pred %p<3>;\n"
"  ld.param.u64 %rd1, [pq];\n"
"  ld.param.u64 %rd2, [pk];\n"
"  ld.param.u64 %rd3, [pscores];\n"
"  ld.param.u32 %r1, [phs];\n"
"  ld.param.u32 %r2, [pT];\n"
"  ld.param.u32 %r3, [pkvdim];\n"
"  mov.u32 %r4, %tid.x;\n"
"  setp.ge.u32 %p1, %r4, %r2;\n"
"  @%p1 bra DONE;\n"
"  mul.lo.u32 %r5, %r4, %r3;\n"
"  mul.wide.u32 %rd4, %r5, 4;\n"
"  add.u64 %rd4, %rd2, %rd4;\n"
"  mov.f32 %f1, 0f00000000;\n"
"  mov.u32 %r6, 0;\n"
"DOT:\n"
"  setp.ge.u32 %p2, %r6, %r1;\n"
"  @%p2 bra DOTD;\n"
"  mul.wide.u32 %rd5, %r6, 4;\n"
"  add.u64 %rd6, %rd1, %rd5;\n"
"  add.u64 %rd7, %rd4, %rd5;\n"
"  ld.global.f32 %f2, [%rd6];\n"
"  ld.global.f32 %f3, [%rd7];\n"
"  mad.f32 %f1, %f2, %f3, %f1;\n"
"  add.u32 %r6, %r6, 1;\n"
"  bra DOT;\n"
"DOTD:\n"
"  cvt.rn.f32.u32 %f4, %r1;\n"
"  sqrt.approx.f32 %f4, %f4;\n"
"  div.approx.f32 %f1, %f1, %f4;\n"
"  mul.wide.u32 %rd8, %r4, 4;\n"
"  add.u64 %rd8, %rd3, %rd8;\n"
"  st.global.f32 [%rd8], %f1;\n"
"DONE:\n"
"  exit;\n"
"}\n"
"\n"
".visible .entry k_softmax(.param .u64 pscores, .param .u32 pT)\n"
"{\n"
"  .reg .u32 %r<12>;\n"
"  .reg .u64 %rd<10>;\n"
"  .reg .f32 %f<10>;\n"
"  .reg .pred %p<4>;\n"
"  .shared .align 4 .f32 sm[128];\n"
"  ld.param.u64 %rd1, [pscores];\n"
"  ld.param.u32 %r2, [pT];\n"
"  mov.u32 %r3, %tid.x;\n"
"  mov.f32 %f5, 0fff7fffff;\n"
"  mov.u32 %r4, %r3;\n"
"MLOOP:\n"
"  setp.ge.u32 %p1, %r4, %r2;\n"
"  @%p1 bra MAFTER;\n"
"  mul.wide.u32 %rd2, %r4, 4;\n"
"  add.u64 %rd3, %rd1, %rd2;\n"
"  ld.global.f32 %f1, [%rd3];\n"
"  max.f32 %f5, %f5, %f1;\n"
"  add.u32 %r4, %r4, 128;\n"
"  bra MLOOP;\n"
"MAFTER:\n"
"  mov.u64 %rd7, sm;\n"
"  mul.wide.u32 %rd8, %r3, 4;\n"
"  add.u64 %rd8, %rd7, %rd8;\n"
"  st.shared.f32 [%rd8], %f5;\n"
"  mov.u32 %r4, 64;\n"
"MR:\n"
"  bar.sync 0;\n"
"  setp.ge.u32 %p2, %r3, %r4;\n"
"  @%p2 bra MRS;\n"
"  mul.wide.u32 %rd5, %r4, 4;\n"
"  add.u64 %rd6, %rd8, %rd5;\n"
"  ld.shared.f32 %f1, [%rd8];\n"
"  ld.shared.f32 %f2, [%rd6];\n"
"  max.f32 %f1, %f1, %f2;\n"
"  st.shared.f32 [%rd8], %f1;\n"
"MRS:\n"
"  shr.u32 %r4, %r4, 1;\n"
"  setp.ne.u32 %p3, %r4, 0;\n"
"  @%p3 bra MR;\n"
"  bar.sync 0;\n"
"  ld.shared.f32 %f5, [%rd7];\n"
"  mov.f32 %f8, 0f00000000;\n"
"  mov.u32 %r4, %r3;\n"
"ELOOP:\n"
"  setp.ge.u32 %p1, %r4, %r2;\n"
"  @%p1 bra EAFTER;\n"
"  mul.wide.u32 %rd2, %r4, 4;\n"
"  add.u64 %rd3, %rd1, %rd2;\n"
"  ld.global.f32 %f1, [%rd3];\n"
"  sub.f32 %f1, %f1, %f5;\n"
"  mul.f32 %f1, %f1, 0f3fb8aa3b;\n"
"  ex2.approx.f32 %f1, %f1;\n"
"  add.f32 %f8, %f8, %f1;\n"
"  add.u32 %r4, %r4, 128;\n"
"  bra ELOOP;\n"
"EAFTER:\n"
"  st.shared.f32 [%rd8], %f8;\n"
"  mov.u32 %r4, 64;\n"
"SR:\n"
"  bar.sync 0;\n"
"  setp.ge.u32 %p2, %r3, %r4;\n"
"  @%p2 bra SRS;\n"
"  mul.wide.u32 %rd5, %r4, 4;\n"
"  add.u64 %rd6, %rd8, %rd5;\n"
"  ld.shared.f32 %f1, [%rd8];\n"
"  ld.shared.f32 %f2, [%rd6];\n"
"  add.f32 %f1, %f1, %f2;\n"
"  st.shared.f32 [%rd8], %f1;\n"
"SRS:\n"
"  shr.u32 %r4, %r4, 1;\n"
"  setp.ne.u32 %p3, %r4, 0;\n"
"  @%p3 bra SR;\n"
"  bar.sync 0;\n"
"  ld.shared.f32 %f8, [%rd7];\n"
"  rcp.approx.f32 %f8, %f8;\n"
"  mov.u32 %r4, %r3;\n"
"NLOOP:\n"
"  setp.ge.u32 %p1, %r4, %r2;\n"
"  @%p1 bra DONE;\n"
"  mul.wide.u32 %rd2, %r4, 4;\n"
"  add.u64 %rd3, %rd1, %rd2;\n"
"  ld.global.f32 %f1, [%rd3];\n"
"  sub.f32 %f1, %f1, %f5;\n"
"  mul.f32 %f1, %f1, 0f3fb8aa3b;\n"
"  ex2.approx.f32 %f1, %f1;\n"
"  mul.f32 %f1, %f1, %f8;\n"
"  st.global.f32 [%rd3], %f1;\n"
"  add.u32 %r4, %r4, 128;\n"
"  bra NLOOP;\n"
"DONE:\n"
"  exit;\n"
"}\n"
"\n"
".visible .entry k_attn_value(.param .u64 pscores, .param .u64 pv, .param .u64 pxb,\n"
"                             .param .u32 phs, .param .u32 pT, .param .u32 pkvdim)\n"
"{\n"
"  .reg .u32 %r<14>;\n"
"  .reg .u64 %rd<12>;\n"
"  .reg .f32 %f<6>;\n"
"  .reg .pred %p<3>;\n"
"  ld.param.u64 %rd1, [pscores];\n"
"  ld.param.u64 %rd2, [pv];\n"
"  ld.param.u64 %rd3, [pxb];\n"
"  ld.param.u32 %r1, [phs];\n"
"  ld.param.u32 %r2, [pT];\n"
"  ld.param.u32 %r3, [pkvdim];\n"
"  mov.u32 %r4, %tid.x;\n"
"  setp.ge.u32 %p1, %r4, %r1;\n"
"  @%p1 bra DONE;\n"
"  mov.f32 %f1, 0f00000000;\n"
"  mov.u32 %r5, 0;\n"
"VLOOP:\n"
"  setp.ge.u32 %p2, %r5, %r2;\n"
"  @%p2 bra VDONE;\n"
"  mul.wide.u32 %rd4, %r5, 4;\n"
"  add.u64 %rd5, %rd1, %rd4;\n"
"  ld.global.f32 %f2, [%rd5];\n"
"  mul.lo.u32 %r6, %r5, %r3;\n"
"  add.u32 %r6, %r6, %r4;\n"
"  mul.wide.u32 %rd6, %r6, 4;\n"
"  add.u64 %rd6, %rd2, %rd6;\n"
"  ld.global.f32 %f3, [%rd6];\n"
"  mad.f32 %f1, %f2, %f3, %f1;\n"
"  add.u32 %r5, %r5, 1;\n"
"  bra VLOOP;\n"
"VDONE:\n"
"  mul.wide.u32 %rd7, %r4, 4;\n"
"  add.u64 %rd7, %rd3, %rd7;\n"
"  st.global.f32 [%rd7], %f1;\n"
"DONE:\n"
"  exit;\n"
"}\n";

#define LOAD(n, s) do { *(FARPROC*)&p_##n = GetProcAddress(h, s); if (!p_##n) { fprintf(stderr, "sm11: missing %s\n", s); return -1; } } while (0)
#define CK(e) do { CUresult _r = (e); if (_r) { fprintf(stderr, "sm11: %s -> %d\n", #e, _r); return -1; } } while (0)

static CUfunction f_matvec, f_rmsnorm, f_add, f_silu, f_rope, f_copy, f_ascores, f_softmax, f_avalue;
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
    LOAD(cuMemcpyDtoD, "cuMemcpyDtoD_v2"); LOAD(cuLaunchKernel, "cuLaunchKernel"); LOAD(cuCtxSynchronize, "cuCtxSynchronize");
    CUdevice dev; CUcontext ctx; CUmodule mod; char name[128]; int ma=0, mi=0; size_t fr=0, tot=0;
    CK(p_cuInit(0)); CK(p_cuDeviceGet(&dev, 0)); CK(p_cuDeviceGetName(name, sizeof name, dev));
    CK(p_cuDeviceComputeCapability(&ma, &mi, dev)); CK(p_cuCtxCreate(&ctx, 0, dev));
    char log[8192] = {0}; int opts[2] = {5, 6}; void* vals[2] = {log, (void*)(size_t)sizeof log};
    CUresult r = p_cuModuleLoadDataEx(&mod, PTX, 2, opts, vals);
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
    CK(p_cuMemGetInfo(&fr, &tot));
    fprintf(stderr, "sm11: %s cc%d.%d vram free %u/%u MiB, weights %u MiB\n", name, ma, mi,
            (unsigned)(fr>>20), (unsigned)(tot>>20), (unsigned)(nbytes>>20));
    g_stage_bytes = 4u << 20;
    /* Prefer fitting the whole always-active model (decision/draft) in VRAM. */
    size_t leave = g_stage_bytes + (16u << 20);
    size_t budget = fr > leave ? fr - leave : (fr > (8u<<20) ? fr - (8u<<20) : 0);
    const char* cap = getenv("SM11_RESIDENT_MIB");
    if (cap) { size_t c = (size_t)atoi(cap) << 20; if (c < budget) budget = c; }
    g_resident = nbytes < budget ? nbytes : budget;
    CK(p_cuMemAlloc(&g_stage, g_stage_bytes));
    if (g_resident) { CK(p_cuMemAlloc(&g_dbase, g_resident)); CK(p_cuMemcpyHtoD(g_dbase, base, g_resident)); }
    g_hbase = (const char*)base; g_nbytes = nbytes; g_ready = 1;
    fprintf(stderr, "sm11: resident %u MiB / %u MiB weights (role: always-active)\n",
            (unsigned)(g_resident>>20), (unsigned)(nbytes>>20));
    return 0;
}

int sm11_matmul(float* xout, const float* x, const float* w, int n, int d) {
    if (!g_ready) return -1;
    CUdeviceptr dx, dy;
    CK(p_cuMemAlloc(&dx, (size_t)n * 4)); CK(p_cuMemAlloc(&dy, (size_t)d * 4));
    CK(p_cuMemcpyHtoD(dx, x, (size_t)n * 4));
    if (matvec_d(dy, dx, w, n, d)) return -1;
    CK(p_cuMemcpyDtoH(xout, dy, (size_t)d * 4));
    p_cuMemFree(dx); p_cuMemFree(dy);
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
    else { CK(p_cuMemcpyHtoD(d_x, erow, (size_t)dim * 4)); }

    int h2 = hs / 2;
    float *cosb = (float*)malloc((size_t)h2 * 4), *sinb = (float*)malloc((size_t)h2 * 4);
    for (int i = 0; i < h2; i++) {
        float freq = 1.0f / powf(10000.0f, (2.0f * i) / (float)hs);
        float val = pos * freq; cosb[i] = cosf(val); sinb[i] = sinf(val);
    }
    CK(p_cuMemcpyHtoD(d_cos, cosb, (size_t)h2 * 4)); CK(p_cuMemcpyHtoD(d_sin, sinb, (size_t)h2 * 4));
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
            void* sargs[] = {&qh, &kh, &d_scores, &uhs2, &uT, &ukvd};
            CK(launch(f_ascores, 1, 128, sargs));
            void* soargs[] = {&d_scores, &uT};
            CK(launch(f_softmax, 1, 128, soargs));
            void* vargs[] = {&d_scores, &vh, &xb, &uhs2, &uT, &ukvd};
            CK(launch(f_avalue, 1, 128, vargs));
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
    if (matvec_d(d_logits, d_x, h_wcls, dim, p->vocab_size)) return -1;
    CK(p_cuCtxSynchronize());
    CK(p_cuMemcpyDtoH(logits_out, d_logits, (size_t)p->vocab_size * 4));
    return 0;
}
