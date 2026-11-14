#include "sm11_compat.h"
#include <stdio.h>
#include <stdlib.h>
typedef int CUresult; typedef void* CUmodule; typedef void* CUfunction; typedef void* CUcontext; typedef int CUdevice;
int main(){
#ifdef _WIN32
  sm11_lib_t h = sm11_dlopen("nvcuda.dll");
#else
  sm11_lib_t h = sm11_dlopen("libcuda.so.1");
  if (!h) h = sm11_dlopen("libcuda.so");
  if (!h) h = sm11_dlopen("/usr/local/lib/libcuda.so.1");
#endif
  if (!h) { fprintf(stderr, "libcuda.so / nvcuda.dll not found\n"); return 1; }
  CUresult (SM11_API *cuInit)(unsigned) = (void*)sm11_dlsym(h,"cuInit");
  CUresult (SM11_API *cuDeviceGet)(CUdevice*,int) = (void*)sm11_dlsym(h,"cuDeviceGet");
  CUresult (SM11_API *cuCtxCreate)(CUcontext*,unsigned,CUdevice) = (void*)sm11_dlsym(h,"cuCtxCreate_v2");
  CUresult (SM11_API *cuModuleLoadDataEx)(CUmodule*,const void*,unsigned,int*,void**) = (void*)sm11_dlsym(h,"cuModuleLoadDataEx");
  CUresult (SM11_API *cuModuleGetFunction)(CUfunction*,CUmodule,const char*) = (void*)sm11_dlsym(h,"cuModuleGetFunction");
  FILE*f=fopen("kernels.ptx","rb"); fseek(f,0,SEEK_END); long n=ftell(f); fseek(f,0,SEEK_SET);
  char*buf=malloc(n+1); fread(buf,1,n,f); buf[n]=0; fclose(f);
  CUdevice d; CUcontext c; CUmodule m; char log[8192]={0}; int opts[2]={5,6}; void*vals[2]={log,(void*)(sizeof log)};
  printf("init %d\n", cuInit(0)); printf("dev %d\n", cuDeviceGet(&d,0)); printf("ctx %d\n", cuCtxCreate(&c,0,d));
  CUresult r=cuModuleLoadDataEx(&m,buf,2,opts,vals); printf("load %d log=%s\n", r, log);
  const char* names[]={"k_matvec","k_rmsnorm","k_add","k_silu_mul","k_rope","k_copy","k_attn_scores","k_softmax","k_attn_value","k_attn_fused",0};
  for(int i=0;names[i];i++){ CUfunction fn; CUresult e=cuModuleGetFunction(&fn,m,names[i]); printf("  %s -> %d\n", names[i], e); }
  return 0;
}
