import sys
p=sys.argv[1]; s=open(p,encoding='utf-8').read()
def rep(a,b):
    global s
    assert a in s, a[:70]; s=s.replace(a,b,1)
rep('fprintf(stderr,"q4m%s %ux%u %s MR=%d: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\\n",sh[s].n',
    'fprintf(stderr,"q4m%s %ux%u %s MR=%d: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\\n",g_v5?"v5":"v4",sh[s].n')
rep("for(int s=0;s<4;s++){ double ref=1e9; for(int t=0;t<2;t++) for(int mi=0;mi<3;mi++){",
    "for(int s=0;s<4;s++){ double ref=1e9; for(int t=1;t<2;t++) for(int mi=0;mi<3;mi++){ if(getenv(\"SMOL_KB_SKIPQ4\")) break;")
rep("static CUfunction f_q4m[2][3], f_q4v[2][3];","static CUfunction f_q4m[2][3], f_q4v[2][3], f_q8m[2][2]; static int g_q8m=2; static unsigned m8cfg[3];")
rep("static CUdeviceptr al(size_t b)", r'''static int qmv8c(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, unsigned RG, unsigned BG, unsigned grid, int mr, int tex){
  unsigned T=RG*BG*8; if(T>512||T<32||(n/32)%BG||d%mr) return 1; unsigned sm=n*4+T*mr*4; if(sm>16000) return 1;
  unsigned ch=(d+RG*mr-1)/(RG*mr); if(grid>ch) grid=ch; unsigned woff=tex?(unsigned)((w-g_ar)/4):0, mode=0;
  void* a[]={&y,&x,&w,&woff,&n,&d,&RG,&BG,&mode};
  return p_cuLaunchKernel(f_q8m[tex][mr==2?0:1], grid,1,1, T,1,1, sm, 0, a, 0); }
static CUdeviceptr al(size_t b)''')
rep("  if(g_mr && !q8 && !nw){", r'''  if(g_q8m && q8 && !nw){ if(!m8cfg[0]){ m8cfg[0]=8; m8cfg[1]=1; m8cfg[2]=64; if(getenv("SMOL_M8CFG")) sscanf(getenv("SMOL_M8CFG"),"%u,%u,%u",&m8cfg[0],&m8cfg[1],&m8cfg[2]); }
    return qmv8c(y,x,w,n,d,m8cfg[0],m8cfg[1],m8cfg[2],g_q8m,g_tex); }
  if(g_mr && !q8 && !nw){''')
rep('    if(getenv("SMOL_V5")) g_v5=atoi(getenv("SMOL_V5"));', r'''    if(getenv("SMOL_V5")) g_v5=atoi(getenv("SMOL_V5"));
    { const char* n8[2][2]={{"k_q8g2","k_q8g4"},{"k_q8t2","k_q8t4"}}; for(int t=0;t<2;t++) for(int m=0;m<2;m++) if(p_cuModuleGetFunction(&f_q8m[t][m],g_sm11_mod,n8[t][m])) g_q8m=0;
      if(getenv("SMOL_Q8M")) g_q8m=atoi(getenv("SMOL_Q8M")); }''')
# kbench: q8 classifier sweep
rep("  occ(\"k_q4f\",f_q4f,64,", r'''  if(gpu_cls && !cls_q4){ unsigned RGs[]={4,8,16}, BGs[]={1,2,3}, Gs[]={64,128,256,512}; int mrs[]={2,4}; unsigned nv=nvocab;
    for(int mi=0;mi<2;mi++){ double best=1e9; unsigned b0=0,b1=0,b2=0;
      for(int i=0;i<3;i++) for(int j=0;j<3;j++) for(int g=0;g<4;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;
        for(int k=0;k<5&&!bad;k++) bad=qmv8c(dLOG,dXN,dEMB,dim,nv,RGs[i],BGs[j],Gs[g],mrs[mi],1); if(p_cuCtxSynchronize()||bad) continue;
        double tt=(now()-t0)*1000/5; if(tt<best){best=tt;b0=RGs[i];b1=BGs[j];b2=Gs[g];} }
      fprintf(stderr,"q8m 576x%u tex MR=%d: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\n",nv,mrs[mi],b0,b1,b2,best,(double)dim/32*34*nv/(best*1e-3)/1e9); } }
  if(getenv("SMOL_KB_ONLYNEW")) return;
  occ("k_q4f",f_q4f,64,''')
open(p,'w',encoding='utf-8').write(s); print("ok")
