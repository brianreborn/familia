import sys
p=sys.argv[1]; s=open(p,encoding='utf-8').read()
def rep(a,b):
    global s
    assert a in s, a[:70]; s=s.replace(a,b,1)
rep("static CUfunction f_q4m[2][3],","static CUfunction f_q4x[9]; static int g_x=0; static unsigned xcfg[4][4];\nstatic CUfunction f_q4m[2][3],")
rep("static CUdeviceptr al(size_t b)", r'''static int qmvx(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, unsigned mode, unsigned RG, unsigned BG, unsigned grid, int mr){
  unsigned T=RG*BG*8; if(T>512||T<32||(n/32)%BG||RG*mr>T||!f_q4x[mr]) return 1; unsigned sm=n*4+mr*RG*(BG*8+1)*4; if(sm>16000) return 1;
  unsigned ch=(d+RG*mr-1)/(RG*mr); if(grid>ch) grid=ch; unsigned woff=(unsigned)((w-g_ar)/4);
  void* a[]={&y,&x,&w,&woff,&n,&d,&RG,&BG,&mode};
  return p_cuLaunchKernel(f_q4x[mr], grid,1,1, T,1,1, sm, 0, a, 0); }
static int xshape(unsigned n,unsigned d){ return n!=576?1:(d==3072?0:(d==960?2:3)); }
static CUdeviceptr al(size_t b)''')
rep("  if(g_mr && !q8 && !nw){", r'''  if(g_x && !q8 && !nw){ int xs=xshape(n,d); unsigned* c2=xcfg[xs]; if(!c2[0]){ unsigned dd[4][4]={{4,8,2,8},{2,8,2,8},{4,4,2,16},{4,4,2,16}}; memcpy(c2,dd[xs],16);
      char k[16]; sprintf(k,"SMOL_XS%d",xs); if(getenv(k)) sscanf(getenv(k),"%u,%u,%u,%u",&c2[0],&c2[1],&c2[2],&c2[3]); }
    return qmvx(y,x,w,n,d,mode,c2[1],c2[2],c2[3],c2[0]); }
  if(g_mr && !q8 && !nw){''')
rep('      if(getenv("SMOL_Q8M")) g_q8m=atoi(getenv("SMOL_Q8M")); }', r'''      if(getenv("SMOL_Q8M")) g_q8m=atoi(getenv("SMOL_Q8M")); }
    for(int m=1;m<=8;m++){ char v[16]; sprintf(v,"k_q4x%d",m); if(p_cuModuleGetFunction(&f_q4x[m],g_sm11_mod,v)) f_q4x[m]=0; }
    g_x = f_q4x[2] && (!getenv("SMOL_X") || atoi(getenv("SMOL_X")));''')
rep("  if(gpu_cls && !cls_q4){ unsigned RGs[]={4,8,16},", r'''  if(getenv("SMOL_KB_X")){ struct {unsigned n,d; CUdeviceptr w,y,x; unsigned mode;} sh[4]={{576,3072,dW[0][4],dHB,dXN,0},{1536,576,dW[0][6],dXB,dHB,2},{576,960,dW[0][0],dQKV,dXN,0},{576,576,dW[0][3],dXB,dXB2,0}};
    unsigned RGs[]={2,4,8,16}, BGs[]={1,2,3,6}, Gs[]={8,16,32}; int mrs[]={1,2,3,4,5,6,8};
    for(int mi=0;mi<7;mi++){ int mr=mrs[mi]; char nm[16]; sprintf(nm,"k_q4x%d",mr); occ(nm,f_q4x[mr],64,576*4+mr*4*17*4);
      for(int s=0;s<4;s++){ double best=1e9; unsigned b0=0,b1=0,b2=0;
        for(int i=0;i<4;i++) for(int j=0;j<4;j++) for(int g=0;g<3;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;
          for(int k=0;k<20&&!bad;k++) bad=qmvx(sh[s].y,sh[s].x,sh[s].w,sh[s].n,sh[s].d,sh[s].mode,RGs[i],BGs[j],Gs[g],mr); if(p_cuCtxSynchronize()||bad) continue;
          double tt=(now()-t0)*1000/20; if(tt<best){best=tt;b0=RGs[i];b1=BGs[j];b2=Gs[g];} }
        fprintf(stderr,"XMR %d %ux%u: RG=%u BG=%u G=%u thr=%u %.3f ms (%.2f GB/s)\n",mr,sh[s].n,sh[s].d,b0,b1,b2,b0*b1*8,best,(double)sh[s].n/32*18*sh[s].d/(best*1e-3)/1e9);
        if(best<1e9) occ("  best",f_q4x[mr],b0*b1*8,sh[s].n*4+mr*b0*(b1*8+1)*4); } }
    return; }
  if(gpu_cls && !cls_q4){ unsigned RGs[]={4,8,16},''')
open(p,'w',encoding='utf-8').write(s); print("ok")
