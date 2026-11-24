#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <windows.h>
#include "sm11_shim.h"
static double ms(void){static LARGE_INTEGER f;static int i;LARGE_INTEGER c;if(!i){QueryPerformanceFrequency(&f);i=1;}QueryPerformanceCounter(&c);return 1000.0*c.QuadPart/f.QuadPart;}
static unsigned short f2h(float v){union{float f;unsigned u;}u;u.f=v;unsigned s=(u.u>>16)&0x8000,e=(u.u>>23)&0xff,m=(u.u>>13)&0x3ff;int ne=(int)e-127+15;if(ne<=0)return s;if(ne>=31)return s|0x7c00;return s|(ne<<10)|m;}
static float h2f(unsigned short h){unsigned s=(h&0x8000)<<16,e=(h>>10)&0x1f,m=h&0x3ff;union{float f;unsigned u;}u;if(!e){u.u=s;return u.f;}u.u=s|((e+112)<<23)|(m<<13);return u.f;}
static void run(int n,int d){
  float*w=malloc((size_t)n*d*4),*x=malloc(n*4),*y0=malloc(d*4),*y1=malloc(d*4);
  for(int i=0;i<n*d;i++) w[i]=sinf(i*0.37f); for(int i=0;i<n;i++) x[i]=cosf(i*0.11f);
  unsigned char*q=malloc((size_t)(n/32)*18*d),*o=q;
  for(int r=0;r<d;r++) for(int b=0;b<n/32;b++){const float*v=w+r*n+b*32;float a=0,mx=0;for(int i=0;i<32;i++)if(fabsf(v[i])>a){a=fabsf(v[i]);mx=v[i];}
    float dd=mx/-8.f; float id=dd?1.f/dd:0; unsigned short h=f2h(dd); memcpy(o,&h,2); o+=2;
    for(int i=0;i<16;i++){int a0=(int)fminf(15,v[i]*id+8.5f),a1=(int)fminf(15,v[i+16]*id+8.5f);*o++=a0|(a1<<4);}}
  /* CPU ref on dequantized weights */
  o=q; for(int r=0;r<d;r++){float s=0; for(int b=0;b<n/32;b++){unsigned short h;memcpy(&h,o,2);float dd=h2f(h);o+=2;for(int i=0;i<16;i++){s+=((o[i]&15)-8)*dd*x[b*32+i]+((o[i]>>4)-8)*dd*x[b*32+i+16];}o+=16;} y0[r]=s;}
  sm11_wmatvec(4,y1,x,q,n,d); float e=0,mxy=0; for(int i=0;i<d;i++){e=fmaxf(e,fabsf(y0[i]-y1[i]));mxy=fmaxf(mxy,fabsf(y0[i]));}
  double t0=ms(); for(int i=0;i<50;i++) sm11_wmatvec(4,y1,x,q,n,d); double t1=ms();
  printf("q4 %dx%d err %.5f (|y|max %.2f) %.3f ms\n",n,d,e,mxy,(t1-t0)/50);
}
int main(void){ if(sm11_register(NULL,0)) return 1; run(576,576); run(576,192); run(576,1536); run(1536,576); printf("cache %u KiB\n",(unsigned)(sm11_wcache_bytes()>>10)); return 0; }
