#include <stdio.h>
#include <stdlib.h>
#include <windows.h>
#include "sm11_shim.h"
static double qpc_ms(void){static LARGE_INTEGER f;static int i;LARGE_INTEGER c;if(!i){QueryPerformanceFrequency(&f);i=1;}QueryPerformanceCounter(&c);return 1000.0*(double)c.QuadPart/(double)f.QuadPart;}
int main(void){
  int n=288,d=768,iters=100,warmup=5;
  size_t wb=(size_t)n*d*4; float*w=malloc(wb); float*x=malloc(n*4u);
  float*y[8]; for(int k=0;k<8;k++) y[k]=malloc(d*4u);
  for(int i=0;i<n*d;i++) w[i]=((i%50)-25)/25.0f; for(int i=0;i<n;i++) x[i]=((i%17)-8)/8.0f;
  if(sm11_register(w,wb)) return 1;
  Sm11Job jobs[8]; for(int k=0;k<8;k++){jobs[k].y=y[k];jobs[k].x=x;jobs[k].w=w;jobs[k].n=n;jobs[k].d=d;}
  double t0,t1;
  for(int i=0;i<warmup;i++) sm11_matvec_batch(jobs,6);
  t0=qpc_ms(); for(int i=0;i<iters;i++) sm11_matvec_batch(jobs,6); t1=qpc_ms();
  double b6=(t1-t0)/iters;
  for(int i=0;i<warmup;i++) for(int k=0;k<6;k++) sm11_matmul(y[k],x,w,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) for(int k=0;k<6;k++) sm11_matmul(y[k],x,w,n,d); t1=qpc_ms();
  double s6=(t1-t0)/iters;
  for(int i=0;i<warmup;i++) sm11_matvec_batch(jobs,8);
  t0=qpc_ms(); for(int i=0;i<iters;i++) sm11_matvec_batch(jobs,8); t1=qpc_ms();
  double b8=(t1-t0)/iters;
  for(int i=0;i<warmup;i++) for(int k=0;k<8;k++) sm11_matmul(y[k],x,w,n,d);
  t0=qpc_ms(); for(int i=0;i<iters;i++) for(int k=0;k<8;k++) sm11_matmul(y[k],x,w,n,d); t1=qpc_ms();
  double s8=(t1-t0)/iters;
  printf("batch6_ms\t%.3f\n3x2_single_ms\t%.3f\nspeedup6\t%.3fx\n", b6,s6,s6/b6);
  printf("batch8_ms\t%.3f\n8x_single_ms\t%.3f\nspeedup8\t%.3fx\n", b8,s8,s8/b8);
  return 0;
}
