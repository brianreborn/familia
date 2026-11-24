/* Microbench: CPU vs sm11 matvec across (n,d) shapes typical of decision/draft models. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "sm11_shim.h"
#include <windows.h>
static long time_in_ms(void){ return (long)GetTickCount(); }
static void cpu_matvec(float* y, const float* x, const float* w, int n, int d){
  for(int i=0;i<d;i++){ float v=0; for(int j=0;j<n;j++) v+=w[i*n+j]*x[j]; y[i]=v; }
}
int main(){
  int shapes[][2]={{64,64},{128,128},{288,288},{288,768},{768,288},{288,32000},{512,512},{1024,1024}};
  int ns=sizeof(shapes)/sizeof(shapes[0]);
  size_t maxb=0; for(int s=0;s<ns;s++){ size_t b=(size_t)shapes[s][0]*shapes[s][1]*4; if(b>maxb)maxb=b; }
  float* blob=(float*)malloc(maxb); float* x=(float*)malloc(1024*4); float* y0=(float*)malloc(32000*4); float* y1=(float*)malloc(32000*4);
  for(size_t i=0;i<maxb/4;i++) blob[i]=(float)((i*17)%100)/50.0f-1;
  for(int i=0;i<1024;i++) x[i]=(float)((i*13)%100)/50.0f-1;
  if(sm11_register(blob,maxb)!=0){ fprintf(stderr,"no gpu\n"); }
  printf("n\td\tcpu_ms\tgpu_ms\tspeedup\tmax_err\n");
  for(int s=0;s<ns;s++){
    int n=shapes[s][0], d=shapes[s][1];
    int iters = (n*d < 200000) ? 200 : 20;
    long t0=time_in_ms();
    for(int i=0;i<iters;i++) cpu_matvec(y0,x,blob,n,d);
    long t1=time_in_ms();
    int gok=1; long t2=time_in_ms();
    for(int i=0;i<iters;i++) if(sm11_matmul(y1,x,blob,n,d)!=0){ gok=0; break; }
    long t3=time_in_ms();
    float err=0; if(gok) for(int i=0;i<d;i++){ float e=y0[i]-y1[i]; if(e<0)e=-e; if(e>err)err=e; }
    double c=(t1-t0)/(double)iters, g=gok?(t3-t2)/(double)iters:-1;
    printf("%d\t%d\t%.3f\t%.3f\t%.2f\t%g\n", n,d,c,g, (g>0?c/g:0), err);
  }
  return 0;
}
