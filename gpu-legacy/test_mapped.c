/* zero-copy mapped host memory probe on sm_11: attribute, ctx MAP_HOST, DEVICEMAP alloc, kernel write, latency vs event */
#include "sm11_shim.c"
static double qn(void){ LARGE_INTEGER f,c; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&c); return (double)c.QuadPart/f.QuadPart; }
int main(void){ setvbuf(stdout,0,_IONBF,0);
  HMODULE h=LoadLibraryA("nvcuda.dll"); CUresult (__stdcall *gattr)(int*,int,CUdevice)=(void*)GetProcAddress(h,"cuDeviceGetAttribute");
  CUresult (__stdcall *hgdp)(CUdeviceptr*,void*,unsigned)=(void*)GetProcAddress(h,"cuMemHostGetDevicePointer_v2");
  if(!hgdp) hgdp=(void*)GetProcAddress(h,"cuMemHostGetDevicePointer");
  _putenv("SM11_CTX_FLAGS=8"); /* CU_CTX_MAP_HOST */
  if(sm11_register(NULL,0)){ printf("init failed\n"); return 1; }
  CUdevice dev=0; int v=-1, integ=-1; gattr(&v,19,dev); gattr(&integ,18,dev);
  printf("CU_DEVICE_ATTRIBUTE_CAN_MAP_HOST_MEMORY=%d INTEGRATED=%d\n",v,integ);
  float* hp=0; CUresult r=p_cuMemHostAlloc((void**)&hp,4096,2 /*DEVICEMAP*/); printf("cuMemHostAlloc(DEVICEMAP)=%d\n",(int)r);
  if(r) return 0; CUdeviceptr dp=0; r=hgdp?hgdp(&dp,hp,0):-1; printf("cuMemHostGetDevicePointer=%d dptr=%llx\n",(int)r,(unsigned long long)dp);
  if(r) return 0;
  for(int i=0;i<256;i++) hp[i]=1.0f; CUdeviceptr dy; p_cuMemAlloc(&dy,1024); float ones[256]; for(int i=0;i<256;i++) ones[i]=2.0f; p_cuMemcpyHtoD(dy,ones,1024);
  unsigned n=256; void* a[]={&dp,&dy,&n}; r=launch(f_add,2,128,a); CUresult s2=p_cuCtxSynchronize();
  printf("kernel add into mapped: launch=%d sync=%d hp[0]=%.1f hp[255]=%.1f (expect 3.0)\n",(int)r,(int)s2,hp[0],hp[255]);
  /* latency: tiny kernel + host spin on mapped value vs event */
  double t=qn(); for(int k=0;k<200;k++){ hp[0]=0; launch(f_add,1,128,a); double t1=qn(); while(((volatile float*)hp)[0]==0.0f){ YieldProcessor(); if(qn()-t1>0.2){ printf("mapped flag never became visible (iter %d)\n",k); k=999; break; } } } double tm=(qn()-t)/200*1e3;
  t=qn(); for(int k=0;k<200;k++){ launch(f_add,1,128,a); sm11_fence(); } double te=(qn()-t)/200*1e3;
  printf("round trip: mapped-flag spin %.3f ms, event fence %.3f ms\n",tm,te);
  return 0; }
