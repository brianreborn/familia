#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
typedef int CUresult; typedef void* CUmodule; typedef void* CUfunction; typedef void* CUcontext; typedef int CUdevice;
int main(){
  HMODULE h=LoadLibraryA("nvcuda.dll");
  CUresult (__stdcall *cuInit)(unsigned)= (void*)GetProcAddress(h,"cuInit");
  CUresult (__stdcall *cuDeviceGet)(CUdevice*,int)=(void*)GetProcAddress(h,"cuDeviceGet");
  CUresult (__stdcall *cuCtxCreate)(CUcontext*,unsigned,CUdevice)=(void*)GetProcAddress(h,"cuCtxCreate_v2");
  CUresult (__stdcall *cuModuleLoadDataEx)(CUmodule*,const void*,unsigned,int*,void**)=(void*)GetProcAddress(h,"cuModuleLoadDataEx");
  CUresult (__stdcall *cuModuleGetFunction)(CUfunction*,CUmodule,const char*)=(void*)GetProcAddress(h,"cuModuleGetFunction");
  FILE*f=fopen("kernels.ptx","rb"); fseek(f,0,SEEK_END); long n=ftell(f); fseek(f,0,SEEK_SET);
  char*buf=malloc(n+1); fread(buf,1,n,f); buf[n]=0; fclose(f);
  CUdevice d; CUcontext c; CUmodule m; char log[8192]={0}; int opts[2]={5,6}; void*vals[2]={log,(void*)(sizeof log)};
  printf("init %d\n", cuInit(0)); printf("dev %d\n", cuDeviceGet(&d,0)); printf("ctx %d\n", cuCtxCreate(&c,0,d));
  CUresult r=cuModuleLoadDataEx(&m,buf,2,opts,vals); printf("load %d log=%s\n", r, log);
  const char* names[]={"k_matvec","k_rmsnorm","k_add","k_silu_mul","k_rope","k_copy","k_attn_scores","k_softmax","k_attn_value","k_attn_fused",0};
  for(int i=0;names[i];i++){ CUfunction fn; CUresult e=cuModuleGetFunction(&fn,m,names[i]); printf("  %s -> %d\n", names[i], e); }
  return 0;
}
