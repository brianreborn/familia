#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <windows.h>
#include "sm11_shim.h"

static double qpc_ms(void) {
  static LARGE_INTEGER f; static int init;
  LARGE_INTEGER c;
  if (!init) { QueryPerformanceFrequency(&f); init = 1; }
  QueryPerformanceCounter(&c);
  return 1000.0 * (double)c.QuadPart / (double)f.QuadPart;
}
static void pack_q4(const float* w, int n, int d, void* out) {
  unsigned char* o = (unsigned char*)out;
  for (int row=0; row<d; row++) for (int b=0; b<n/32; b++) {
    const float* x = w + row*n + b*32;
    float amax=0; for(int i=0;i<32;i++){ float v=fabsf(x[i]); if(v>amax)amax=v; }
    float dscale = amax>0?amax/7.0f:1e-6f;
    union { float f; unsigned u; } u; u.f = dscale;
    unsigned s=(u.u>>16)&0x8000, e=((u.u>>23)&0xff), m=(u.u>>13)&0x3ff;
    int ne=(int)e-127+15; unsigned short h;
    if(ne<=0) h=(unsigned short)s; else if(ne>=31) h=(unsigned short)(s|0x7c00);
    else h=(unsigned short)(s|(ne<<10)|m);
    memcpy(o, &h, 2); o+=2;
    for(int i=0;i<16;i++){
      int q0=(int)lrintf(x[i]/dscale)+8; if(q0<0)q0=0; if(q0>15)q0=15;
      int q1=(int)lrintf(x[i+16]/dscale)+8; if(q1<0)q1=0; if(q1>15)q1=15;
      *o++ = (unsigned char)(q0 | (q1<<4));
    }
  }
}
static void pack_q8(const float* w, int n, int d, void* out) {
  unsigned char* o=(unsigned char*)out;
  for(int row=0;row<d;row++) for(int b=0;b<n/32;b++){
    const float* x=w+row*n+b*32; float amax=0;
    for(int i=0;i<32;i++){ float v=fabsf(x[i]); if(v>amax)amax=v; }
    float ds=amax>0?amax/127.0f:1e-6f;
    union{float f; unsigned u;}u; u.f=ds;
    unsigned s=(u.u>>16)&0x8000, e=(u.u>>23)&0xff, m=(u.u>>13)&0x3ff;
    int ne=(int)e-127+15; unsigned short h;
    if(ne<=0)h=(unsigned short)s; else if(ne>=31)h=(unsigned short)(s|0x7c00); else h=(unsigned short)(s|(ne<<10)|m);
    memcpy(o,&h,2); o+=2;
    for(int i=0;i<32;i++){ int q=(int)lrintf(x[i]/ds); if(q<-128)q=-128; if(q>127)q=127; *o++=(unsigned char)(signed char)q; }
  }
}
static void cpu_f32(float*y,const float*x,const float*w,int n,int d){
  for(int i=0;i<d;i++){ float v=0; for(int j=0;j<n;j++) v+=w[i*n+j]*x[j]; y[i]=v; }
}
static float max_abs_err(const float*a,const float*b,int n){
  float m=0; for(int i=0;i<n;i++){ float e=fabsf(a[i]-b[i]); if(e>m)m=e; } return m;
}

int main(void){
  int n=288,d=768,iters=100,warmup=5;
  size_t wbytes=(size_t)n*d*4;
  float*w=malloc(wbytes); float*x=malloc((size_t)n*4);
  float*y0=malloc((size_t)d*4); float*y1=malloc((size_t)d*4);
  float*y2=malloc((size_t)d*4); float*y3=malloc((size_t)d*4);
  for(int i=0;i<(int)(n*d);i++) w[i]=((i%50)-25)/25.0f;
  for(int i=0;i<n;i++) x[i]=((i%17)-8)/8.0f;
  size_t q4b=(size_t)(n/32)*18*d, q8b=(size_t)(n/32)*34*d;
  void*q4=malloc(q4b); void*q8=malloc(q8b);
  pack_q4(w,n,d,q4); pack_q8(w,n,d,q8);

  /* Register W so matvec_d hits resident path (no per-call W H2D). */
  if(sm11_register(w, wbytes)!=0){ fprintf(stderr,"no gpu\n"); return 1; }

  cpu_f32(y0,x,w,n,d);
  { float mx=0,mn=0; for(int i=0;i<d;i++){ if(y0[i]>mx)mx=y0[i]; if(y0[i]<mn)mn=y0[i]; }
    printf("cpu_y_range\t%.3f\t%.3f\n", mn, mx); }
  if(sm11_matmul(y1,x,w,n,d)) return 2;
  printf("err_f32\t%.6f\n", max_abs_err(y0,y1,d));
  if(sm11_q4_matmul(y1,x,q4,n,d)) return 3;
  printf("err_q4\t%.6f\n", max_abs_err(y0,y1,d));
  if(sm11_q8_matmul(y1,x,q8,n,d)) return 4;
  printf("err_q8\t%.6f\n", max_abs_err(y0,y1,d));
  Sm11Job jobs[3]={{y1,x,w,n,d},{y2,x,w,n,d},{y3,x,w,n,d}};
  if(sm11_matvec_batch(jobs,3)) return 5;
  printf("err_batch\t%.6f\n", max_abs_err(y0,y1,d));

  double t0,t1;
  for(int i=0;i<warmup;i++) cpu_f32(y0,x,w,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) cpu_f32(y0,x,w,n,d); t1=qpc_ms();
  printf("cpu_f32_ms\t%.3f\n",(t1-t0)/iters);

  for(int i=0;i<warmup;i++) sm11_matmul(y1,x,w,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) sm11_matmul(y1,x,w,n,d); t1=qpc_ms();
  printf("gpu_f32_resident_ms\t%.3f\n",(t1-t0)/iters);

  for(int i=0;i<warmup;i++) sm11_q4_matmul(y1,x,q4,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) sm11_q4_matmul(y1,x,q4,n,d); t1=qpc_ms();
  printf("gpu_q4_ms\t%.3f\n",(t1-t0)/iters);

  for(int i=0;i<warmup;i++) sm11_q8_matmul(y1,x,q8,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) sm11_q8_matmul(y1,x,q8,n,d); t1=qpc_ms();
  printf("gpu_q8_ms\t%.3f\n",(t1-t0)/iters);

  for(int i=0;i<warmup;i++) sm11_matvec_batch(jobs,3);
  t0=qpc_ms(); for(int i=0;i<iters;i++) sm11_matvec_batch(jobs,3); t1=qpc_ms();
  double batch=(t1-t0)/iters; printf("gpu_batch3_ms\t%.3f\n", batch);

  for(int i=0;i<warmup;i++){ sm11_matmul(y1,x,w,n,d); sm11_matmul(y2,x,w,n,d); sm11_matmul(y3,x,w,n,d); }
  t0=qpc_ms(); for(int i=0;i<iters;i++){ sm11_matmul(y1,x,w,n,d); sm11_matmul(y2,x,w,n,d); sm11_matmul(y3,x,w,n,d);} t1=qpc_ms();
  double singles=(t1-t0)/iters; printf("gpu_3x_single_ms\t%.3f\n", singles);
  printf("batch_speedup\t%.3fx\n", batch>0?singles/batch:0);
  printf("launch_save_ms\t%.3f\n", singles-batch);
  return 0;
}
