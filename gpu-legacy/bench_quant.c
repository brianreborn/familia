#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <windows.h>
#include "sm11_shim.h"
static double qpc_ms(void){static LARGE_INTEGER f;static int i;LARGE_INTEGER c;if(!i){QueryPerformanceFrequency(&f);i=1;}QueryPerformanceCounter(&c);return 1000.0*(double)c.QuadPart/(double)f.QuadPart;}
static void pack_q4(const float* w,int n,int d,void* out){
  unsigned char* o=(unsigned char*)out;
  for(int row=0;row<d;row++) for(int b=0;b<n/32;b++){
    const float* x=w+row*n+b*32; float amax=0; for(int i=0;i<32;i++){float v=fabsf(x[i]); if(v>amax)amax=v;}
    float ds=amax>0?amax/7.0f:1e-6f; union{float f;unsigned u;}u;u.f=ds;
    unsigned s=(u.u>>16)&0x8000,e=(u.u>>23)&0xff,m=(u.u>>13)&0x3ff; int ne=(int)e-127+15; unsigned short h;
    if(ne<=0)h=(unsigned short)s; else if(ne>=31)h=(unsigned short)(s|0x7c00); else h=(unsigned short)(s|(ne<<10)|m);
    memcpy(o,&h,2); o+=2;
    for(int i=0;i<16;i++){ int q0=(int)lrintf(x[i]/ds)+8; if(q0<0)q0=0; if(q0>15)q0=15;
      int q1=(int)lrintf(x[i+16]/ds)+8; if(q1<0)q1=0; if(q1>15)q1=15; *o++=(unsigned char)(q0|(q1<<4)); }
  }
}
static void pack_q8(const float* w,int n,int d,void* out){
  unsigned char* o=(unsigned char*)out;
  for(int row=0;row<d;row++) for(int b=0;b<n/32;b++){
    const float* x=w+row*n+b*32; float amax=0; for(int i=0;i<32;i++){float v=fabsf(x[i]); if(v>amax)amax=v;}
    float ds=amax>0?amax/127.0f:1e-6f; union{float f;unsigned u;}u;u.f=ds;
    unsigned s=(u.u>>16)&0x8000,e=(u.u>>23)&0xff,m=(u.u>>13)&0x3ff; int ne=(int)e-127+15; unsigned short h;
    if(ne<=0)h=(unsigned short)s; else if(ne>=31)h=(unsigned short)(s|0x7c00); else h=(unsigned short)(s|(ne<<10)|m);
    memcpy(o,&h,2); o+=2;
    for(int i=0;i<32;i++){ int q=(int)lrintf(x[i]/ds); if(q<-128)q=-128; if(q>127)q=127; *o++=(unsigned char)(signed char)q; }
  }
}
static void cpu_f32(float*y,const float*x,const float*w,int n,int d){ for(int i=0;i<d;i++){ float v=0; for(int j=0;j<n;j++) v+=w[i*n+j]*x[j]; y[i]=v; } }
static float maxerr(const float*a,const float*b,int n){ float m=0; for(int i=0;i<n;i++){ float e=fabsf(a[i]-b[i]); if(e>m)m=e;} return m; }
static void bench_shape(int n,int d,int iters){
  size_t wb=(size_t)n*d*4; float*w=malloc(wb); float*x=malloc((size_t)n*4);
  float*y0=malloc((size_t)d*4); float*y1=malloc((size_t)d*4);
  for(int i=0;i<n*d;i++) w[i]=((i%50)-25)/25.0f; for(int i=0;i<n;i++) x[i]=((i%17)-8)/8.0f;
  size_t q4b=(size_t)(n/32)*18*d, q8b=(size_t)(n/32)*34*d;
  void*q4=malloc(q4b); void*q8=malloc(q8b); pack_q4(w,n,d,q4); pack_q8(w,n,d,q8);
  /* re-register so F32 W is resident; also warms q4/q8 resident cache */
  if(sm11_register(w,wb)!=0){ printf("no gpu\n"); return; }
  cpu_f32(y0,x,w,n,d);
  sm11_matmul(y1,x,w,n,d); printf("shape %dx%d err_f32 %.6f\n",n,d,maxerr(y0,y1,d));
  sm11_q4_matmul(y1,x,q4,n,d); printf("  err_q4 %.6f\n",maxerr(y0,y1,d));
  sm11_q8_matmul(y1,x,q8,n,d); printf("  err_q8 %.6f\n",maxerr(y0,y1,d));
  double t0,t1; int warm=5;
  for(int i=0;i<warm;i++) cpu_f32(y0,x,w,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) cpu_f32(y0,x,w,n,d); t1=qpc_ms();
  double cpu=(t1-t0)/iters;
  for(int i=0;i<warm;i++) sm11_matmul(y1,x,w,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) sm11_matmul(y1,x,w,n,d); t1=qpc_ms();
  double f32=(t1-t0)/iters;
  for(int i=0;i<warm;i++) sm11_q4_matmul(y1,x,q4,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) sm11_q4_matmul(y1,x,q4,n,d); t1=qpc_ms();
  double q4t=(t1-t0)/iters;
  for(int i=0;i<warm;i++) sm11_q8_matmul(y1,x,q8,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) sm11_q8_matmul(y1,x,q8,n,d); t1=qpc_ms();
  double q8t=(t1-t0)/iters;
  printf("  cpu_f32_ms %.3f  gpu_f32_ms %.3f  gpu_q4_ms %.3f  gpu_q8_ms %.3f\n", cpu,f32,q4t,q8t);
  printf("  q4_vs_cpu %.2fx  q4_vs_f32gpu %.2fx\n", q4t/cpu, q4t/f32);
  free(w); free(x); free(y0); free(y1); free(q4); free(q8);
}
int main(void){
  if(sm11_register(NULL,0)!=0){ fprintf(stderr,"no gpu\n"); return 1; }
  bench_shape(288,768,100);
  bench_shape(512,1536,50);
  bench_shape(1024,1024,30);
  return 0;
}
