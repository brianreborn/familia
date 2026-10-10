import re,sys
p=sys.argv[1]; s=open(p,encoding='utf-8').read()
# kernels + texref globals
s=s.replace("static CUdeviceptr dQKV, dXN;","static CUdeviceptr dQKV, dXN;\nstatic CUfunction f_q4m[2][3]; static int g_mr=0, g_tex=1; static unsigned mcfg[4][3];\n#define MRI(m) ((m)==1?0:(m)==2?1:2)",1)
s=s.replace("static CUdeviceptr al(size_t b)", r'''static int qmvmc(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, unsigned mode, unsigned RG, unsigned BG, unsigned grid, int mr, int tex){
  unsigned T=RG*BG*8; if(T>512||T<32||(n/32)%BG||d%mr) return 1; unsigned sm=n*4+T*mr*4; if(sm>16000) return 1;
  unsigned ch=(d+RG*mr-1)/(RG*mr); if(grid>ch) grid=ch; unsigned woff=(unsigned)((w-g_ar)/4);
  void* a[]={&y,&x,&w,&woff,&n,&d,&RG,&BG,&mode};
  return p_cuLaunchKernel(f_q4m[tex][MRI(mr)], grid,1,1, T,1,1, sm, 0, a, 0); }
static CUdeviceptr al(size_t b)''',1)
# route q4 no-norm calls
s=s.replace("  return qmvfc(y,x,w,n,d,q8,nw,mode,fcfgR[c],fcfgL[c],fcfgG[c]); }",
r'''  if(g_mr && !q8 && !nw){ if(!mcfg[c][0]){ unsigned dd[4][3]={{4,2,64},{4,2,64},{4,2,64},{4,2,64}}; memcpy(mcfg[c],dd[c],12);
      char k[32]; sprintf(k,"SMOL_MCFG%d",c); if(getenv(k)) sscanf(getenv(k),"%u,%u,%u",&mcfg[c][0],&mcfg[c][1],&mcfg[c][2]); }
    return qmvmc(y,x,w,n,d,mode,mcfg[c][0],mcfg[c][1],mcfg[c][2],g_mr,g_tex); }
  return qmvfc(y,x,w,n,d,q8,nw,mode,fcfgR[c],fcfgL[c],fcfgG[c]); }''',1)
# bind texture once to the whole arena
s=s.replace('failed\\n",g_arsz>>20); exit(2);}', r'''failed\n",g_arsz>>20); exit(2);}
  { HMODULE hc=GetModuleHandleA("nvcuda.dll"); CUresult (__stdcall *gtr)(void**,CUmodule,const char*)=(void*)GetProcAddress(hc,"cuModuleGetTexRef");
    CUresult (__stdcall *sfmt)(void*,int,int)=(void*)GetProcAddress(hc,"cuTexRefSetFormat"); CUresult (__stdcall *sadr)(size_t*,void*,CUdeviceptr,size_t)=(void*)GetProcAddress(hc,"cuTexRefSetAddress_v2");
    if(!sadr) sadr=(void*)GetProcAddress(hc,"cuTexRefSetAddress");
    int ok=1; const char* nm[2][3]={{"k_q4g1","k_q4g2","k_q4g4"},{"k_q4t1","k_q4t2","k_q4t4"}};
    for(int t=0;t<2;t++) for(int m=0;m<3;m++) if(p_cuModuleGetFunction(&f_q4m[t][m],g_sm11_mod,nm[t][m])) ok=0;
    void* tr=0; size_t off=1; CUresult r1=gtr?gtr(&tr,g_sm11_mod,"tw_q4"):999, r2=r1?999:sfmt(tr,0x03,1), r3=r2?999:sadr(&off,tr,g_ar,g_arsz);
    fprintf(stderr,"q4m kernels %s, texref get=%d fmt=%d bind=%d off=%zu (%zu MiB = %zu texels)\n",ok?"ok":"MISSING",(int)r1,(int)r2,(int)r3,off,g_arsz>>20,g_arsz/4);
    if(r3||off) g_tex=0; if(getenv("SMOL_TEX")) g_tex=atoi(getenv("SMOL_TEX")); g_mr=getenv("SMOL_MR")?atoi(getenv("SMOL_MR")):0; if(!ok) g_mr=0; }''',1)
# kbench sweep
s=s.replace("static void kbench(void){ unsigned dim=c_dim, hd=c_hd; int N=200; double a;", r'''static void kbench(void){ unsigned dim=c_dim, hd=c_hd; int N=200; double a;
  { struct {unsigned n,d; CUdeviceptr w,y,x; unsigned mode;} sh[4]={{576,3072,dW[0][4],dHB,dXN,0},{1536,576,dW[0][6],dXB,dHB,2},{576,960,dW[0][0],dQKV,dXN,0},{576,576,dW[0][3],dXB,dXB2,0}};
    unsigned RGs[]={1,2,4,8,16}, BGs[]={1,2,3,6}, Gs[]={8,16,32,64,128}; int mrs[]={1,2,4};
    for(int s=0;s<4;s++){ double ref=1e9; for(int t=0;t<2;t++) for(int mi=0;mi<3;mi++){ double best=1e9; unsigned b0=0,b1=0,b2=0;
      for(int i=0;i<5;i++) for(int j=0;j<4;j++) for(int g=0;g<5;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;
        for(int k=0;k<50&&!bad;k++) bad=qmvmc(sh[s].y,sh[s].x,sh[s].w,sh[s].n,sh[s].d,sh[s].mode,RGs[i],BGs[j],Gs[g],mrs[mi],t); if(p_cuCtxSynchronize()||bad) continue;
        double tt=(now()-t0)*1000/50; if(tt<best){best=tt;b0=RGs[i];b1=BGs[j];b2=Gs[g];} }
      double gbs=(double)sh[s].n/32*18*sh[s].d/(best*1e-3)/1e9;
      fprintf(stderr,"q4m %ux%u %s MR=%d: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\n",sh[s].n,sh[s].d,t?"tex":"gld",mrs[mi],b0,b1,b2,best,gbs); } } }''',1)
open(p,'w',encoding='utf-8').write(s)
print(s.count("qmvmc"), "tw_q4" in s)
