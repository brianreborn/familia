import sys
p=sys.argv[1]; s=open(p,encoding='utf-8').read()
def rep(a,b):
    global s
    assert a in s, a[:70]; s=s.replace(a,b,1)
# rotating cold benchmark: every call uses the next layer's matrix (like a real token)
rep("    unsigned RGs[]={2,4,8,16}, BGs[]={1,2,3,6}, Gs[]={8,16,32}; int mrs[]={1,2,3,4,5,6,8};",
    "    unsigned RGs[]={2,4,8,16}, BGs[]={1,2,3,6}, Gs[]={8,16,32}; int mrs[]={1,2,3,4,5,6,8}; int wi[4]={4,6,0,3}; int IT=2*c_nl;\n"
    "    for(int s=0;s<4;s++) for(int mr=2;mr<=4;mr+=2){ unsigned rg8[]={4,8,16}, bg8[]={1,2}, g8[]={8,16,32,64}; double best=1e9; unsigned b0=0,b1=0,b2=0;\n"
    "      for(int i=0;i<3;i++) for(int j=0;j<2;j++) for(int g=0;g<4;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;\n"
    "        for(int k=0;k<IT&&!bad;k++) bad=qmvmc(sh[s].y,sh[s].x,dW[k%c_nl][wi[s]],sh[s].n,sh[s].d,sh[s].mode,rg8[i],bg8[j],g8[g],mr,1); if(p_cuCtxSynchronize()||bad) continue;\n"
    "        double tt=(now()-t0)*1000/IT; if(tt<best){best=tt;b0=rg8[i];b1=bg8[j];b2=g8[g];} }\n"
    "      fprintf(stderr,\"COLD v4 MR=%d %ux%u: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\\n\",mr,sh[s].n,sh[s].d,b0,b1,b2,best,(double)sh[s].n/32*18*sh[s].d/(best*1e-3)/1e9); }")
rep("for(int k=0;k<20&&!bad;k++) bad=qmvx(sh[s].y,sh[s].x,sh[s].w,", "for(int k=0;k<IT&&!bad;k++) bad=qmvx(sh[s].y,sh[s].x,dW[k%c_nl][wi[s]],")
rep("double tt=(now()-t0)*1000/20; if(tt<best){best=tt;b0=RGs[i];b1=BGs[j];b2=Gs[g];} }\n        fprintf(stderr,\"XMR %d",
    "double tt=(now()-t0)*1000/IT; if(tt<best){best=tt;b0=RGs[i];b1=BGs[j];b2=Gs[g];} }\n        fprintf(stderr,\"COLD x MR=%d")
# q4 classifier (GPU fallback when Q8 table doesn't fit) sweep
rep("    return; }\n  if(gpu_cls && !cls_q4){", r'''    if(gpu_cls && cls_q4){ unsigned nv=nvocab; unsigned rg8[]={4,8,16}, bg8[]={1,2}, g8[]={16,64,256};
      for(int v=0;v<2;v++) for(int mr=2;mr<=(v?5:4);mr+=(v?1:2)){ double best=1e9; unsigned b0=0,b1=0,b2=0;
        for(int i=0;i<3;i++) for(int j=0;j<2;j++) for(int g=0;g<3;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;
          for(int k=0;k<3&&!bad;k++) bad= v? qmvx(dLOG,dXN,dEMB,dim,nv,0,rg8[i],bg8[j],g8[g],mr) : qmvmc(dLOG,dXN,dEMB,dim,nv,0,rg8[i],bg8[j],g8[g],mr,1); if(p_cuCtxSynchronize()||bad) continue;
          double tt=(now()-t0)*1000/3; if(tt<best){best=tt;b0=rg8[i];b1=bg8[j];b2=g8[g];} }
        fprintf(stderr,"CLSQ4 %s MR=%d: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\n",v?"x":"v4",mr,b0,b1,b2,best,(double)dim/32*18*nv/(best*1e-3)/1e9); } }
    return; }
  if(gpu_cls && !cls_q4){''')
open(p,'w',encoding='utf-8').write(s); print("ok")
