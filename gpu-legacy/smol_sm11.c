/* smol_sm11: SmolLM2 (llama, GQA) GGUF Q4_0 full-forward on sm_11, one sync per token.
   Also a CPU reference forward (same math) for end-to-end checks.
   usage: smol_sm11 model.gguf "id,id,..." ngen [cpu|gpu|both] */
#include "sm11_shim.c"
#include <math.h>
#include <stdint.h>
#include <time.h>

typedef struct { char name[96]; int nd; uint64_t ne[4]; int type; uint64_t off; void* data; } T;
static unsigned char* G; static T tens[512]; static int ntens;
static char** vocab; static int nvocab;
static int c_dim, c_hd, c_nl, c_nh, c_nkv, c_ctx = 128; static float c_base = 10000.f, c_eps = 1e-5f;

static uint64_t rd64(unsigned char** p){ uint64_t v; memcpy(&v,*p,8); *p+=8; return v; }
static uint32_t rd32(unsigned char** p){ uint32_t v; memcpy(&v,*p,4); *p+=4; return v; }
static int tsz(int t){ int s[]={1,1,2,2,4,4,4,1,0,0,8,8,8}; return (t<=12)?s[t]:0; }
static void skipval(unsigned char** p, int t){
  if (t==8){ uint64_t n=rd64(p); *p+=n; return; }
  if (t==9){ int et=rd32(p); uint64_t n=rd64(p); for(uint64_t i=0;i<n;i++) skipval(p,et); return; }
  *p += tsz(t);
}
static float f16f(uint16_t h){ uint32_t s=(h&0x8000)<<16, e=(h>>10)&31, m=h&0x3ff, b;
  if(!e) { float r = ldexpf((float)m, -24); return s? -r : r; }
  if(e==31) b=s|0x7f800000|(m<<13); else b=s|((e+112)<<23)|(m<<13); float f; memcpy(&f,&b,4); return f; }
static T* gt(const char* n){ for(int i=0;i<ntens;i++) if(!strcmp(tens[i].name,n)) return &tens[i];
  fprintf(stderr,"missing tensor %s\n",n); exit(1); }
static T* gl(int l, const char* s){ char b[96]; sprintf(b,"blk.%d.%s",l,s); return gt(b); }
static size_t tbytes(T* t){ uint64_t n=t->ne[0]; for(int i=1;i<t->nd;i++) n*=t->ne[i];
  if(t->type==0) return n*4; if(t->type==2) return n/32*18; if(t->type==8) return n/32*34; return 0; }

static void load(const char* path){
  FILE* f=fopen(path,"rb"); if(!f){perror(path);exit(1);} fseek(f,0,SEEK_END); long long sz=_ftelli64(f); fseek(f,0,SEEK_SET);
  G=malloc(sz); fread(G,1,sz,f); fclose(f);
  unsigned char* p=G+4; rd32(&p); uint64_t nt=rd64(&p), nkv=rd64(&p); uint32_t align=32;
  for(uint64_t i=0;i<nkv;i++){ uint64_t kl=rd64(&p); char k[256]; memcpy(k,p,kl<255?kl:255); k[kl<255?kl:255]=0; p+=kl; int t=rd32(&p);
    if(t==9 && !strcmp(k,"tokenizer.ggml.tokens")){ int et=rd32(&p); uint64_t n=rd64(&p); nvocab=(int)n; vocab=malloc(n*sizeof(char*));
      for(uint64_t j=0;j<n;j++){ uint64_t sl=rd64(&p); vocab[j]=malloc(sl+1); memcpy(vocab[j],p,sl); vocab[j][sl]=0; p+=sl; } (void)et; continue; }
    if(t==4||t==5){ uint32_t v; memcpy(&v,p,4); float fv; memcpy(&fv,p,4);
      if(strstr(k,".embedding_length")) c_dim=v; else if(strstr(k,".feed_forward_length")) c_hd=v;
      else if(strstr(k,".block_count")) c_nl=v; else if(strstr(k,".attention.head_count_kv")) c_nkv=v;
      else if(strstr(k,".attention.head_count")) c_nh=v; else if(!strcmp(k,"general.alignment")) align=v; }
    if(t==6){ float fv; memcpy(&fv,p,4); if(strstr(k,"rope.freq_base")) c_base=fv; if(strstr(k,"layer_norm_rms_epsilon")) c_eps=fv; }
    skipval(&p,t); }
  ntens=(int)nt;
  for(int i=0;i<ntens;i++){ uint64_t nl=rd64(&p); memcpy(tens[i].name,p,nl); tens[i].name[nl]=0; p+=nl; tens[i].nd=rd32(&p);
    for(int d=0;d<tens[i].nd;d++) tens[i].ne[d]=rd64(&p); tens[i].type=rd32(&p); tens[i].off=rd64(&p); }
  uint64_t base=(uint64_t)(p-G); base=(base+align-1)/align*align;
  for(int i=0;i<ntens;i++) tens[i].data=G+base+tens[i].off;
  fprintf(stderr,"model: dim %d hd %d L %d heads %d kv %d vocab %d base %.0f eps %g\n",c_dim,c_hd,c_nl,c_nh,c_nkv,nvocab,c_base,c_eps);
}
/* ---- CPU reference ---- */
static void mv_cpu(float* y, const float* x, T* w, int n, int d){
  int nb=n/32;
  for(int r=0;r<d;r++){ float acc=0;
    if(w->type==0){ const float* wr=(const float*)w->data+(size_t)r*n; for(int i=0;i<n;i++) acc+=wr[i]*x[i]; }
    else if(w->type==2){ const unsigned char* b=(const unsigned char*)w->data+(size_t)r*nb*18;
      for(int k=0;k<nb;k++,b+=18){ uint16_t h; memcpy(&h,b,2); float s=0; const float* xx=x+k*32;
        for(int j=0;j<16;j++){ s+=((b[2+j]&15)-8)*xx[j]+((b[2+j]>>4)-8)*xx[j+16]; } acc+=s*f16f(h); } }
    else { const unsigned char* b=(const unsigned char*)w->data+(size_t)r*nb*34;
      for(int k=0;k<nb;k++,b+=34){ uint16_t h; memcpy(&h,b,2); float s=0; const float* xx=x+k*32; const signed char* q=(const signed char*)b+2;
        for(int j=0;j<32;j++) s+=q[j]*xx[j]; acc+=s*f16f(h); } }
    y[r]=acc; } }
static void embed(float* x, int tok){ T* e=gt("token_embd.weight"); int nb=c_dim/32; const unsigned char* b=(const unsigned char*)e->data+(size_t)tok*nb*34;
  for(int k=0;k<nb;k++,b+=34){ uint16_t h; memcpy(&h,b,2); float s=f16f(h); for(int j=0;j<32;j++) x[k*32+j]=((const signed char*)b)[2+j]*s; } }
static void rms(float* o,const float* x,const float* w,int n){ float ss=0; for(int i=0;i<n;i++) ss+=x[i]*x[i]; ss=1.f/sqrtf(ss/n+c_eps); for(int i=0;i<n;i++) o[i]=w[i]*x[i]*ss; }
static float *ccos,*csin;
static float *kc,*vc,*X,*XB,*XB2,*Q,*HB,*HB2,*ATT,*LOG;
static void rope_cpu(float* v,int n,int pos){ int hs=c_dim/c_nh; for(int i=0;i<n;i+=2){ int j=(i%hs)/2; float c=ccos[pos*(hs/2)+j], s=csin[pos*(hs/2)+j];
  float a=v[i],b=v[i+1]; v[i]=a*c-b*s; v[i+1]=a*s+b*c; } }
static void fwd_cpu(int tok,int pos){
  int dim=c_dim, hs=dim/c_nh, kvd=hs*c_nkv, km=c_nh/c_nkv;
  embed(X,tok);
  for(int l=0;l<c_nl;l++){ float* K=kc+((size_t)l*c_ctx+pos)*kvd; float* V=vc+((size_t)l*c_ctx+pos)*kvd;
    rms(XB,X,(float*)gl(l,"attn_norm.weight")->data,dim);
    mv_cpu(Q,XB,gl(l,"attn_q.weight"),dim,dim); mv_cpu(K,XB,gl(l,"attn_k.weight"),dim,kvd); mv_cpu(V,XB,gl(l,"attn_v.weight"),dim,kvd);
    rope_cpu(Q,dim,pos); rope_cpu(K,kvd,pos);
    for(int h=0;h<c_nh;h++){ float* q=Q+h*hs; float mx=-1e30f,sum=0;
      for(int t=0;t<=pos;t++){ float* k=kc+((size_t)l*c_ctx+t)*kvd+(h/km)*hs; float s=0; for(int i=0;i<hs;i++) s+=q[i]*k[i]; s/=sqrtf((float)hs); ATT[t]=s; if(s>mx)mx=s; }
      for(int t=0;t<=pos;t++){ ATT[t]=expf(ATT[t]-mx); sum+=ATT[t]; }
      float* o=XB+h*hs; for(int i=0;i<hs;i++) o[i]=0;
      for(int t=0;t<=pos;t++){ float* v=vc+((size_t)l*c_ctx+t)*kvd+(h/km)*hs; float a=ATT[t]/sum; for(int i=0;i<hs;i++) o[i]+=a*v[i]; } }
    mv_cpu(XB2,XB,gl(l,"attn_output.weight"),dim,dim); for(int i=0;i<dim;i++) X[i]+=XB2[i];
    rms(XB,X,(float*)gl(l,"ffn_norm.weight")->data,dim);
    mv_cpu(HB,XB,gl(l,"ffn_gate.weight"),dim,c_hd); mv_cpu(HB2,XB,gl(l,"ffn_up.weight"),dim,c_hd);
    for(int i=0;i<c_hd;i++){ float g=HB[i]; HB[i]=g/(1.f+expf(-g))*HB2[i]; }
    mv_cpu(XB,HB,gl(l,"ffn_down.weight"),c_hd,dim); for(int i=0;i<dim;i++) X[i]+=XB[i]; }
  rms(X,X,(float*)gt("output_norm.weight")->data,dim);
  mv_cpu(LOG,X,gt("token_embd.weight"),dim,nvocab);
}
/* ---- GPU full forward ---- */
static CUfunction f_q4r, f_q8r, f_q4f, f_q8f, f_ropekv, f_attnmh; static int g_fused=1, g_prenorm=0; static CUdeviceptr dQKV, dXN;
static CUfunction f_q4x[9]; static int g_x=0; static unsigned xcfg[5][4];
static CUfunction f_q4m[2][3], f_q4v[2][3], f_q8m[2][2]; static int g_q8m=4; static unsigned m8cfg[3]; static int g_v5=0; /* v5 slower end-to-end until re-swept */ static int g_mr=0, g_tex=1; static unsigned mcfg[4][3];
static int qmvmc(CUdeviceptr,CUdeviceptr,CUdeviceptr,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,int,int);
static int qmv8c(CUdeviceptr,CUdeviceptr,CUdeviceptr,unsigned,unsigned,unsigned,unsigned,unsigned,int,int);
static int qmvx(CUdeviceptr,CUdeviceptr,CUdeviceptr,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,int);
static int xshape(unsigned,unsigned);
#define MRI(m) ((m)==1?0:(m)==2?1:2)
static CUdeviceptr dW[32][9], dN[32][2], dON, dEMB, dX, dXB, dXB2, dQ, dHB, dHB2, dKC, dVC, dCOS, dSIN, dLOG;
static int gpu_cls; static int g_inflight=1;
static size_t g_vram_used;
#ifndef DEF_R0
#define DEF_R0 16
#define DEF_L0 8
#define DEF_G0 8
#define DEF_R1 8
#define DEF_L1 24
#define DEF_G1 8
#define DEF_R2 8
#define DEF_L2 16
#define DEF_G2 16
#endif
static unsigned cfgR[5]={0},cfgL[5]={0},cfgG[5]={0};
static int cidx(unsigned n,int q8){ return q8?2:(n==576?0:1); }
static int qmvc(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, int q8, unsigned R, unsigned L, unsigned grid){
  unsigned rb=n/32*(q8?34:18); unsigned sm=n*4+R*rb+128+R*L*4;
  unsigned ch=(d+R-1)/R; if(grid>ch) grid=ch;
  void* a[]={&y,&x,&w,&n,&d,&R,&L};
  return p_cuLaunchKernel(q8?f_q8r:f_q4r, grid,1,1, R*L,1,1, sm, 0, a, 0); }
#define PFW 1000  /* v3: no register prefetch */
static unsigned fcfgR[4],fcfgL[4],fcfgG[4];
static int qmvfc(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, int q8, CUdeviceptr nw, unsigned mode, unsigned R, unsigned L, unsigned grid){
  unsigned rb=n/32*(q8?34:18);
  while(((R*rb+64+3)/4 + R*L-1)/(R*L) > PFW) L*=2;          /* register prefetch capacity */
  if(R*L>512) return 1;
  unsigned sm=n*4+R*rb+128+R*L*4; if(sm>16000) return 1;
  unsigned ch=(d+R-1)/R; if(grid>ch) grid=ch;
  void* a[]={&y,&x,&w,&n,&d,&R,&L,&nw,&mode};
  return p_cuLaunchKernel(q8?f_q8f:f_q4f, grid,1,1, R*L,1,1, sm, 0, a, 0); }
static int qmvf(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, int q8, CUdeviceptr nw, unsigned mode){
  int c = q8?2:(n!=576?1:(d>4096?3:0));
  if(!fcfgR[c]){ unsigned dR[4]={32,8,8,16}, dL[4]={8,24,16,8}, dG[4]={4,4,128,32};  /* v3 sweep 2026-10-10 */ fcfgR[c]=dR[c]; fcfgL[c]=dL[c]; fcfgG[c]=dG[c];
    char k[32]; sprintf(k,"SMOL_FCFG%d",c); if(getenv(k)) sscanf(getenv(k),"%u,%u,%u",&fcfgR[c],&fcfgL[c],&fcfgG[c]); }
  if(g_q8m && q8 && !nw){ if(!m8cfg[0]){ m8cfg[0]=8; m8cfg[1]=1; m8cfg[2]=64; if(getenv("SMOL_M8CFG")) sscanf(getenv("SMOL_M8CFG"),"%u,%u,%u",&m8cfg[0],&m8cfg[1],&m8cfg[2]); }
    return qmv8c(y,x,w,n,d,m8cfg[0],m8cfg[1],m8cfg[2],g_q8m,g_tex); }
  if(g_x && !q8 && !nw){ int xs=xshape(n,d); unsigned* c2=xcfg[xs]; if(!c2[0]){ unsigned dd[5][4]={{5,16,2,8},{5,16,2,32},{5,16,2,8},{5,16,2,8},{3,8,2,8}} /* replay (real launch order) tuning 2026-10-10: MR,RG,BG,G */; memcpy(c2,dd[xs],16);
      char k[16]; sprintf(k,"SMOL_XS%d",xs); if(getenv(k)) sscanf(getenv(k),"%u,%u,%u,%u",&c2[0],&c2[1],&c2[2],&c2[3]); }
    return qmvx(y,x,w,n,d,mode,c2[1],c2[2],c2[3],c2[0]); }
  if(g_mr && !q8 && !nw){ if(!mcfg[c][0]){ unsigned dd[4][3]={{8,1,16},{8,2,8},{8,1,16},{8,1,16}} /* v4 sweep 2026-10-10 */; memcpy(mcfg[c],dd[c],12);
      char k[32]; sprintf(k,"SMOL_MCFG%d",c); if(getenv(k)) sscanf(getenv(k),"%u,%u,%u",&mcfg[c][0],&mcfg[c][1],&mcfg[c][2]); }
    return qmvmc(y,x,w,n,d,mode,mcfg[c][0],mcfg[c][1],mcfg[c][2],g_mr,g_tex); }
  return qmvfc(y,x,w,n,d,q8,nw,mode,fcfgR[c],fcfgL[c],fcfgG[c]); }
static int qmv(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, int q8){
  int c=cidx(n,q8); if(d>4096) c=q8?2:3;
  if(!cfgR[c]){ /* defaults tuned by SMOL_KBENCH sweep */
    unsigned dR[4]={DEF_R0,DEF_R1,DEF_R2,16}, dL[4]={DEF_L0,DEF_L1,DEF_L2,8}, dG[4]={DEF_G0,DEF_G1,DEF_G2,32};
    cfgR[c]=dR[c]; cfgL[c]=dL[c]; cfgG[c]=dG[c];
    char k[32]; sprintf(k,"SMOL_CFG%d",c); if(getenv(k)) sscanf(getenv(k),"%u,%u,%u",&cfgR[c],&cfgL[c],&cfgG[c]); }
  return qmvc(y,x,w,n,d,q8,cfgR[c],cfgL[c],cfgG[c]); }
static CUdeviceptr g_ar; static size_t g_arsz, g_aroff;
static int qmvmc(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, unsigned mode, unsigned RG, unsigned BG, unsigned grid, int mr, int tex){
  unsigned T=RG*BG*8; if(T>512||T<32||(n/32)%BG||d%mr||(g_v5&&RG*mr>T)) return 1; unsigned sm=g_v5? n*4+mr*RG*(BG*8+1)*4 : n*4+T*mr*4; if(sm>16000) return 1;
  unsigned ch=(d+RG*mr-1)/(RG*mr); if(grid>ch) grid=ch; unsigned woff=tex?(unsigned)((w-g_ar)/4):0;
  void* a[]={&y,&x,&w,&woff,&n,&d,&RG,&BG,&mode};
  return p_cuLaunchKernel((g_v5?f_q4v:f_q4m)[tex][MRI(mr)], grid,1,1, T,1,1, sm, 0, a, 0); }
static int qmv8c(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, unsigned RG, unsigned BG, unsigned grid, int mr, int tex){
  unsigned T=RG*BG*8; if(T>512||T<32||(n/32)%BG||d%mr) return 1; unsigned sm=n*4+T*mr*4; if(sm>16000) return 1;
  unsigned ch=(d+RG*mr-1)/(RG*mr); if(grid>ch) grid=ch; unsigned woff=tex?(unsigned)((w-g_ar)/4):0, mode=0;
  void* a[]={&y,&x,&w,&woff,&n,&d,&RG,&BG,&mode};
  return p_cuLaunchKernel(f_q8m[tex][mr==2?0:1], grid,1,1, T,1,1, sm, 0, a, 0); }
static int g_dry;
static int qmvx(CUdeviceptr y, CUdeviceptr x, CUdeviceptr w, unsigned n, unsigned d, unsigned mode, unsigned RG, unsigned BG, unsigned grid, int mr){
  unsigned T=RG*BG*8; if(T>512||T<32||(n/32)%BG||RG*mr>T||!f_q4x[mr]) return 1;
  { static int rgs[9]; if(!rgs[mr]){ CUresult (__stdcall *ga)(int*,int,CUfunction)=(void*)GetProcAddress(GetModuleHandleA("nvcuda.dll"),"cuFuncGetAttribute"); ga(&rgs[mr],4,f_q4x[mr]); } if((unsigned)rgs[mr]*T>8192) return 1; }  /* would fail with 701 */
  if(g_dry) return 0; unsigned sm=n*4+mr*RG*(BG*8+1)*4; if(sm>16000) return 1;
  unsigned ch=(d+RG*mr-1)/(RG*mr); if(grid>ch) grid=ch; unsigned woff=(unsigned)((w-g_ar)/4);
  void* a[]={&y,&x,&w,&woff,&n,&d,&RG,&BG,&mode};
  return p_cuLaunchKernel(f_q4x[mr], grid,1,1, T,1,1, sm, 0, a, 0); }
static int xshape(unsigned n,unsigned d){ return n!=576?1:(d>4096?4:(d==3072?0:(d==960?2:3))); }
static CUdeviceptr al(size_t b){ b=(b+255)&~(size_t)255; if(g_aroff+b>g_arsz){fprintf(stderr,"arena overflow\n");exit(1);} CUdeviceptr d=g_ar+g_aroff; g_aroff+=b; g_vram_used+=b; return d; }
static CUdeviceptr upb(const void* p,size_t b){ CUdeviceptr d=al(b); p_cuMemcpyHtoD(d,p,b); return d; }
static CUdeviceptr up(T* t){ return upb(t->data,tbytes(t)); }
static int cls_q4; static unsigned char* emb_q4;
static void requant_q4(void){ T* e=gt("token_embd.weight"); int nb=c_dim/32; size_t nbl=(size_t)nvocab*nb; emb_q4=malloc(nbl*18);
  const unsigned char* s=e->data; for(size_t i=0;i<nbl;i++,s+=34){ uint16_t h; memcpy(&h,s,2); float d=f16f(h), v[32], amax=0, mx=0;
    for(int j=0;j<32;j++){ v[j]=((const signed char*)s)[2+j]*d; if(fabsf(v[j])>amax){amax=fabsf(v[j]); mx=v[j];} }
    float dd=mx/-8.f, id=dd?1.f/dd:0; unsigned char* o=emb_q4+i*18; _Float16 hf=(_Float16)dd; memcpy(o,&hf,2);
    for(int j=0;j<16;j++){ int a=(int)(v[j]*id+8.5f), b=(int)(v[j+16]*id+8.5f); if(a>15)a=15; if(b>15)b=15; if(a<0)a=0; if(b<0)b=0; o[2+j]=(unsigned char)(a|(b<<4)); } } }
static const char* wn[9]={"attn_q.weight","attn_k.weight","attn_v.weight","attn_output.weight","ffn_gate.weight","ffn_up.weight","ffn_down.weight"};
static void gpu_setup(void){
  sm11_register(NULL,0);
  g_fused = !getenv("SMOL_FUSED") || atoi(getenv("SMOL_FUSED"));
  if(g_fused && (p_cuModuleGetFunction(&f_q4f,g_sm11_mod,"k_q4f")||p_cuModuleGetFunction(&f_q8f,g_sm11_mod,"k_q8f")||p_cuModuleGetFunction(&f_ropekv,g_sm11_mod,"k_rope_kv")||p_cuModuleGetFunction(&f_attnmh,g_sm11_mod,"k_attn_mh"))){fprintf(stderr,"fused kernels missing\n");exit(1);}
  if(p_cuModuleGetFunction(&f_q4r,g_sm11_mod,"k_q4r")||p_cuModuleGetFunction(&f_q8r,g_sm11_mod,"k_q8r")){fprintf(stderr,"k_q4r/k_q8r missing\n");exit(1);}
  size_t fr,tot; p_cuMemGetInfo(&fr,&tot); size_t margin=(size_t)(getenv("SM11_VRAM_MARGIN_MIB")?atoi(getenv("SM11_VRAM_MARGIN_MIB")):16)<<20;
  fprintf(stderr,"vram free %zu MiB / %zu MiB, margin %zu MiB\n",fr>>20,tot>>20,margin>>20);
  int dim=c_dim, hs=dim/c_nh, kvd=hs*c_nkv;
  size_t need=0; for(int l=0;l<c_nl;l++) for(int k=0;k<7;k++) need+=tbytes(gl(l,wn[k]));
  need += (size_t)2*c_nl*c_ctx*kvd*4 + (size_t)(6*dim+2*c_hd)*4 + c_ctx*hs*4 + (size_t)nvocab*4 + c_nl*2*dim*4;
  if(fr < need+margin){ fprintf(stderr,"layers need %zu MiB + margin > free; abort\n",need>>20); exit(2);}
  T* e=gt("token_embd.weight"); const char* cm=getenv("SMOL_CLS"); size_t eq8=tbytes(e), eq4=eq8/34*18;
  need += (size_t)(g_inflight-1)*2*c_nl*c_ctx*kvd*4;
  size_t tot_need=need+ (size_t)c_nl*9*256 + 64*256 + 8192; size_t cls_b=0;
  if(!cm||!strcmp(cm,"q8")) { if(fr>=tot_need+eq8+margin){ gpu_cls=1; cls_b=eq8; } }
  if(!gpu_cls && (!cm||!strcmp(cm,"q4"))) { if(fr>=tot_need+eq4+margin){ gpu_cls=1; cls_q4=1; cls_b=eq4; } }
  g_arsz=tot_need+cls_b; if(p_cuMemAlloc(&g_ar,g_arsz)){ fprintf(stderr,"arena alloc %zu MiB failed\n",g_arsz>>20); exit(2);}
  { HMODULE hc=GetModuleHandleA("nvcuda.dll"); CUresult (__stdcall *gtr)(void**,CUmodule,const char*)=(void*)GetProcAddress(hc,"cuModuleGetTexRef");
    CUresult (__stdcall *sfmt)(void*,int,int)=(void*)GetProcAddress(hc,"cuTexRefSetFormat"); CUresult (__stdcall *sadr)(size_t*,void*,CUdeviceptr,size_t)=(void*)GetProcAddress(hc,"cuTexRefSetAddress_v2");
    if(!sadr) sadr=(void*)GetProcAddress(hc,"cuTexRefSetAddress");
    int ok=1; const char* nm[2][3]={{"k_q4g1","k_q4g2","k_q4g4"},{"k_q4t1","k_q4t2","k_q4t4"}};
    for(int t=0;t<2;t++) for(int m=0;m<3;m++){ char v[16]; sprintf(v,"k_q4v%s",nm[t][m]+4); if(p_cuModuleGetFunction(&f_q4m[t][m],g_sm11_mod,nm[t][m])||p_cuModuleGetFunction(&f_q4v[t][m],g_sm11_mod,v)) ok=0; }
    if(getenv("SMOL_V5")) g_v5=atoi(getenv("SMOL_V5"));
    { const char* n8[2][2]={{"k_q8g2","k_q8g4"},{"k_q8t2","k_q8t4"}}; for(int t=0;t<2;t++) for(int m=0;m<2;m++) if(p_cuModuleGetFunction(&f_q8m[t][m],g_sm11_mod,n8[t][m])) g_q8m=0;
      if(getenv("SMOL_Q8M")) g_q8m=atoi(getenv("SMOL_Q8M")); }
    for(int m=1;m<=8;m++){ char v[16]; sprintf(v,"k_q4x%d",m); if(p_cuModuleGetFunction(&f_q4x[m],g_sm11_mod,v)) f_q4x[m]=0; }
    g_x = f_q4x[2] && (!getenv("SMOL_X") || atoi(getenv("SMOL_X")));  /* on: cold-tuned per-shape MR (+1.5% e2e) */
    void* tr=0; size_t off=1; CUresult r1=gtr?gtr(&tr,g_sm11_mod,"tw_q4"):999, r2=r1?999:sfmt(tr,0x03,1), r3=r2?999:sadr(&off,tr,g_ar,g_arsz);
    fprintf(stderr,"q4m kernels %s, texref get=%d fmt=%d bind=%d off=%zu (%zu MiB = %zu texels)\n",ok?"ok":"MISSING",(int)r1,(int)r2,(int)r3,off,g_arsz>>20,g_arsz/4);
    if(r3||off) g_tex=0; if(getenv("SMOL_TEX")) g_tex=atoi(getenv("SMOL_TEX")); g_mr=getenv("SMOL_MR")?atoi(getenv("SMOL_MR")):2; if(!ok) g_mr=0; }
  for(int l=0;l<c_nl;l++){ for(int k=0;k<7;k++) dW[l][k]=up(gl(l,wn[k])); dN[l][0]=up(gl(l,"attn_norm.weight")); dN[l][1]=up(gl(l,"ffn_norm.weight")); }
  dON=up(gt("output_norm.weight"));
  dX=al(dim*4); dXB=al(dim*4); dXB2=al(dim*4); dQ=al(dim*4); dHB=al(c_hd*4*2); dHB2=dHB+(CUdeviceptr)c_hd*4; dQKV=al((dim+2*kvd)*4); dXN=al(dim*4); g_prenorm = !getenv("SMOL_PRENORM") || atoi(getenv("SMOL_PRENORM"));  /* default on: norm once per token */ dLOG=al((size_t)nvocab*4);
  dKC=al((size_t)c_nl*c_ctx*kvd*4); dVC=al((size_t)c_nl*c_ctx*kvd*4);
  dCOS=al(c_ctx*hs/2*4); dSIN=al(c_ctx*hs/2*4); p_cuMemcpyHtoD(dCOS,ccos,c_ctx*hs/2*4); p_cuMemcpyHtoD(dSIN,csin,c_ctx*hs/2*4);
  if(gpu_cls){ if(cls_q4){ requant_q4(); dEMB=upb(emb_q4,eq4);} else dEMB=up(e); }
  p_cuMemGetInfo(&fr,&tot);
  fprintf(stderr,"resident %zu MiB (classifier on %s), free after %zu MiB\n",g_vram_used>>20,gpu_cls?(cls_q4?"GPU q4_0 requant":"GPU q8_0"):"CPU q8_0",fr>>20);
}
#define CKL(x) do{ if(x){ fprintf(stderr,"cu err %d line %d\n",(int)(x),__LINE__); exit(3);} }while(0)
static double now(void); static double t_cls;
typedef struct { CUdeviceptr kc, vc; float* plog; float* px; CUevent_ ev; int tok, pos, inflight;  float* pe[2]; int pei, pretok; double t_enq; } Seq;
static void seq_init(Seq* q, int first){ size_t kvb=(size_t)c_nl*c_ctx*(c_dim/c_nh*c_nkv)*4;
  if(first){ q->kc=dKC; q->vc=dVC; } else { q->kc=al(kvb); q->vc=al(kvb); }
  if(p_cuMemHostAlloc((void**)&q->plog,(size_t)nvocab*4,0)||p_cuMemHostAlloc((void**)&q->px,c_dim*4,0)||p_cuEventCreate(&q->ev,2)){fprintf(stderr,"pinned/event alloc failed\n");exit(3);} q->inflight=0; for(int i=0;i<2;i++) if(p_cuMemHostAlloc((void**)&q->pe[i],c_dim*4,0)){fprintf(stderr,"pinned alloc failed\n");exit(3);} q->pei=0; q->pretok=-1; }
static int g_waitmode=1; /* 0: spin64+block (old)  1: bounded useful work, then spin64, then block  2: pure spin (latency floor) */
static struct __attribute__((aligned(64))) { long long chunks, spins, blocks, prehits, nwait; double lat_sum, lat_max; char _p[8]; } g_hs;
static float* g_pemb[2]; static int g_pembi;
/* enqueue one token's whole forward; no host wait. Results land in q->plog / q->px (pinned) when q->ev fires */
static void enqueue_gpu(Seq* sq, int tok, int pos){
  unsigned dim=c_dim, hs=dim/c_nh, kvd=hs*c_nkv, km=c_nh/c_nkv, hd=c_hd; CUdeviceptr dKC_=sq->kc, dVC_=sq->vc;
  sq->pei^=1; float* pe=sq->pe[sq->pei]; if(sq->pretok!=tok) embed(pe,tok); else g_hs.prehits++; sq->pretok=-1; CKL(p_cuMemcpyHtoDAsync(dX,pe,dim*4,0));
  CUdeviceptr cs=dCOS+(CUdeviceptr)pos*(hs/2)*4, sn=dSIN+(CUdeviceptr)pos*(hs/2)*4;
  if(g_fused){ unsigned km_=km, T1=pos+1, qkvd=dim+2*kvd, hd2=2*hd; CUdeviceptr z=0;
    for(int l=0;l<c_nl;l++){
      CUdeviceptr lk=dKC_+(CUdeviceptr)l*c_ctx*kvd*4, lv=dVC_+(CUdeviceptr)l*c_ctx*kvd*4;
      CUdeviceptr K=lk+(CUdeviceptr)pos*kvd*4, V=lv+(CUdeviceptr)pos*kvd*4;
      if(g_prenorm){ void* a[]={&dXN,&dX,&dN[l][0],&dim}; CKL(launch(f_rmsnorm,1,128,a)); CKL(qmvf(dQKV,dXN,dW[l][0],dim,qkvd,0,z,0)); }  /* norm once per token */
      else CKL(qmvf(dQKV,dX,dW[l][0],dim,qkvd,0,dN[l][0],0));                       /* rmsnorm + Wq|Wk|Wv */
      { void* a[]={&dQKV,&dQ,&K,&V,&cs,&sn,&dim,&kvd,&hs}; CKL(launch(f_ropekv,(qkvd/2+127)/128,128,a)); }  /* rope + KV store */
      { void* a[]={&dQ,&lk,&lv,&dXB,&hs,&T1,&kvd,&km_}; CKL(p_cuLaunchKernel(f_attnmh,c_nh,1,1,128,1,1,0,0,a,0)); }  /* all heads */
      CKL(qmvf(dX,dXB,dW[l][3],dim,dim,0,z,1));                                 /* Wo + residual */
      if(g_prenorm){ void* a[]={&dXN,&dX,&dN[l][1],&dim}; CKL(launch(f_rmsnorm,1,128,a)); CKL(qmvf(dHB,dXN,dW[l][4],dim,hd2,0,z,0)); }
      else CKL(qmvf(dHB,dX,dW[l][4],dim,hd2,0,dN[l][1],0));                         /* rmsnorm + Wgate|Wup */
      CKL(qmvf(dX,dHB,dW[l][6],hd,dim,0,z,3));                                  /* silu(g)*u + Wdown + residual */
    }
    if(gpu_cls && !cls_q4){ unsigned nv=nvocab; if(g_prenorm){ void* a[]={&dXN,&dX,&dON,&dim}; CKL(launch(f_rmsnorm,1,128,a)); CKL(qmvf(dLOG,dXN,dEMB,dim,nv,1,z,0)); } else CKL(qmvf(dLOG,dX,dEMB,dim,nv,1,dON,0)); CKL(p_cuMemcpyDtoHAsync(sq->plog,dLOG,(size_t)nvocab*4,0)); CKL(p_cuEventRecord(sq->ev,0)); sq->t_enq=now(); sq->inflight=1; sq->tok=tok; sq->pos=pos; return; }
    goto FINAL; }
  for(int l=0;l<c_nl;l++){
    CUdeviceptr lk=dKC_+(CUdeviceptr)l*c_ctx*kvd*4, lv=dVC_+(CUdeviceptr)l*c_ctx*kvd*4;
    CUdeviceptr K=lk+(CUdeviceptr)pos*kvd*4, V=lv+(CUdeviceptr)pos*kvd*4;
    { void* a[]={&dXB,&dX,&dN[l][0],&dim}; CKL(launch(f_rmsnorm,1,128,a)); }
    CKL(qmv(dQ,dXB,dW[l][0],dim,dim,0)); CKL(qmv(K,dXB,dW[l][1],dim,kvd,0)); CKL(qmv(V,dXB,dW[l][2],dim,kvd,0));
    { void* a[]={&dQ,&K,&cs,&sn,&dim,&hs,&kvd}; CKL(launch(f_rope,(dim/2+127)/128,128,a)); }
    unsigned T1=pos+1;
    for(unsigned h=0;h<(unsigned)c_nh;h++){ CUdeviceptr qh=dQ+h*hs*4, kh=lk+(h/km)*hs*4, vh=lv+(h/km)*hs*4, xb=dXB+h*hs*4;
      void* a[]={&qh,&kh,&vh,&xb,&hs,&T1,&kvd}; CKL(launch(f_attn_fused,1,128,a)); }
    CKL(qmv(dXB2,dXB,dW[l][3],dim,dim,0));
    { void* a[]={&dX,&dXB2,&dim}; CKL(launch(f_add,(dim+127)/128,128,a)); }
    { void* a[]={&dXB,&dX,&dN[l][1],&dim}; CKL(launch(f_rmsnorm,1,128,a)); }
    CKL(qmv(dHB,dXB,dW[l][4],dim,hd,0)); CKL(qmv(dHB2,dXB,dW[l][5],dim,hd,0));
    { void* a[]={&dHB,&dHB2,&hd}; CKL(launch(f_silu,(hd+127)/128,128,a)); }
    CKL(qmv(dXB,dHB,dW[l][6],hd,dim,0));
    { void* a[]={&dX,&dXB,&dim}; CKL(launch(f_add,(dim+127)/128,128,a)); }
  }
FINAL:
  { void* a[]={&dX,&dX,&dON,&dim}; CKL(launch(f_rmsnorm,1,128,a)); }
  if(gpu_cls){ unsigned nv=nvocab; CKL(qmv(dLOG,dX,dEMB,dim,nv,cls_q4?0:1)); CKL(p_cuMemcpyDtoHAsync(sq->plog,dLOG,(size_t)nvocab*4,0)); }
  CKL(p_cuMemcpyDtoHAsync(sq->px,dX,dim*4,0));
  CKL(p_cuEventRecord(sq->ev,0)); sq->t_enq=now(); sq->inflight=1; sq->tok=tok; sq->pos=pos;  /* fix: q4-classifier path had no timestamp */
}
#if !defined(FS_PAD) || FS_PAD
static long long g_polls __attribute__((aligned(64))); static char g_polls_pad[56] __attribute__((unused));
#else
static long long g_polls;
#endif
typedef int (*WorkFn)(void*);
/* pre-embed the next (already known) token into this seq's free pinned buffer: the buffer last used by token N-1, whose H2D is complete */
static int pre_embed(Seq* q, int tok){ if(q->pretok==tok) return 0; embed(q->pe[q->pei^1],tok); q->pretok=tok; return 1; }
static int seq_ready(Seq* q){ CUresult r=p_cuEventQuery(q->ev); if(r==600) return 0; CKL(r); return 1; }
static void seq_wait_w(Seq* q, WorkFn fn, void* ctx){
  if(g_waitmode==2){ while(!seq_ready(q)) YieldProcessor(); goto done; }
  if(g_waitmode==1 && fn){ while(fn(ctx)){ g_hs.chunks++; if(seq_ready(q)) goto done; } }   /* each chunk ~10-50 us */
  for(int k=0;k<64;k++){ if(seq_ready(q)) goto done; g_hs.spins++; YieldProcessor(); }
  g_hs.blocks++; p_cuEventSynchronize(q->ev);
done: { double l=(now()-q->t_enq)*1000; g_hs.lat_sum+=l; if(l>g_hs.lat_max) g_hs.lat_max=l; g_hs.nwait++; } }
static void seq_wait(Seq* q){ seq_wait_w(q,0,0); }
/* host side of a finished token: classifier (CPU) or exact Q8 rescoring of GPU top-K; argmax */
static int finish_gpu(Seq* sq){
  int dim=c_dim; double a=now(); sq->inflight=0;
  if(!gpu_cls){ mv_cpu(LOG,sq->px,gt("token_embd.weight"),dim,nvocab); }
  else if(cls_q4){ enum{K=64}; int ci[K]; float cv[K]; int nk=0; const float* L=sq->plog;
    int m=0; for(int i=0;i<nvocab;i++){ float v=L[i]; if(nk<K){ ci[nk]=i; cv[nk++]=v; if(nk==K){ m=0; for(int j=1;j<K;j++) if(cv[j]<cv[m]) m=j; } continue; } if(v>cv[m]){ cv[m]=v; ci[m]=i; m=0; for(int j=1;j<K;j++) if(cv[j]<cv[m]) m=j; } }
    T* e=gt("token_embd.weight"); T row=*e; int nb=dim/32; int best=ci[0]; float bv=-1e30f;
    for(int j=0;j<nk;j++){ float v; row.data=(unsigned char*)e->data+(size_t)ci[j]*nb*34; mv_cpu(&v,sq->px,&row,dim,1); if(v>bv||(v==bv&&ci[j]<best)){bv=v;best=ci[j];} }
    t_cls+=now()-a; return best; }
  else memcpy(LOG,sq->plog,(size_t)nvocab*4);
  int b=0; for(int i=1;i<nvocab;i++) if(LOG[i]>LOG[b]) b=i; t_cls+=now()-a; return b; }
static Seq g_seq[2];
typedef struct { Seq* q; int next; } RunW;
static int run_work(void* c){ RunW* w=c; if(w->next<0) return 0; int t=w->next; w->next=-1; return pre_embed(w->q,t); }
static int fwd_gpu_tok2(int tok,int pos,int next){ Seq* q=&g_seq[0]; enqueue_gpu(q,tok,pos); RunW w={q,next}; seq_wait_w(q,run_work,&w); return finish_gpu(q); }
static int fwd_gpu_tok(int tok,int pos){ return fwd_gpu_tok2(tok,pos,-1); }
static void occ(const char* nm, CUfunction f, unsigned thr, unsigned smem){
  CUresult (__stdcall *ga)(int*,int,CUfunction)=(void*)GetProcAddress(GetModuleHandleA("nvcuda.dll"),"cuFuncGetAttribute");
  int regs=-1, ssm=-1, lmem=-1; if(ga){ ga(&regs,4,f); ga(&ssm,1,f); ga(&lmem,3,f); }
  int regblk = ((regs*thr+255)/256)*256; /* sm_1x: reg alloc granularity 256/block (approx) */
  int b1 = regblk? 8192/regblk : 8, b2 = 16384/(smem+ssm+16), b3 = 768/thr; int b=b1<b2?b1:b2; if(b3<b)b=b3; if(b>8)b=8;
  fprintf(stderr,"occ %-10s regs/thr=%d lmem=%d static_smem=%d | %u thr, %u dyn smem -> %d CTA/SM (%d thr, %.0f%% of 768)  [limits: regs %d smem %d thr %d]\n",nm,regs,lmem,ssm,thr,smem,b,b*thr,100.0*b*thr/768,b1,b2,b3); }
static void kbench(void){ unsigned dim=c_dim, hd=c_hd; int N=200; double a;
  if(getenv("SMOL_KB_REPLAY")){ /* replay the real token: full enqueue_gpu forward, coordinate descent over per-shape (MR,RG,BG,G) */
    Seq* q=&g_seq[0]; int NT=getenv("SMOL_KB_NT")?atoi(getenv("SMOL_KB_NT")):6; int MRs[]={2,3,4,5,6}; unsigned RGs[]={4,8,16}, BGs[]={1,2}, Gs[]={8,16,32};
    #define TOKMS() ({ p_cuCtxSynchronize(); double t0_=now(); int ok_=1; for(int k_=0;k_<NT;k_++){ enqueue_gpu(q,1+k_,10); } if(p_cuCtxSynchronize()) ok_=0; ok_? (now()-t0_)*1000/NT : 1e9; })
    for(int k=0;k<2;k++) TOKMS();
    fprintf(stderr,"REPLAY start %.2f ms/token\n",TOKMS());
    for(int pass=0;pass<2;pass++) for(int s=0;s<5;s++){ if(s==4 && !(gpu_cls&&cls_q4)) continue; unsigned bc[4]; memcpy(bc,xcfg[s],16); double best=TOKMS();
      for(int m=0;m<5;m++) for(int i=0;i<3;i++) for(int j=0;j<2;j++) for(int g=0;g<3;g++){ unsigned c[4]={MRs[m],RGs[i],BGs[j],Gs[g]}; { unsigned nn[5]={576,1536,576,576,576}, dd2[5]={3072,576,960,576,(unsigned)nvocab}; g_dry=1; int bad=qmvx(0,0,g_ar,nn[s],dd2[s],0,c[1],c[2],c[3],c[0]); g_dry=0; if(bad) continue; }
        memcpy(xcfg[s],c,16); double t=TOKMS(); if(t<best){best=t; memcpy(bc,c,16);} }
      memcpy(xcfg[s],bc,16); fprintf(stderr,"REPLAY pass %d shape %d best MR=%u RG=%u BG=%u G=%u -> %.2f ms/token\n",pass,s,bc[0],bc[1],bc[2],bc[3],best); }
    return; }  { struct {unsigned n,d; CUdeviceptr w,y,x; unsigned mode;} sh[4]={{576,3072,dW[0][4],dHB,dXN,0},{1536,576,dW[0][6],dXB,dHB,2},{576,960,dW[0][0],dQKV,dXN,0},{576,576,dW[0][3],dXB,dXB2,0}};
    unsigned RGs[]={1,2,4,8,16}, BGs[]={1,2,3,6}, Gs[]={8,16,32,64,128}; int mrs[]={1,2,4};
    for(int s=0;s<4;s++){ double ref=1e9; for(int t=1;t<2;t++) for(int mi=0;mi<3;mi++){ if(getenv("SMOL_KB_SKIPQ4")) break; double best=1e9; unsigned b0=0,b1=0,b2=0;
      for(int i=0;i<5;i++) for(int j=0;j<4;j++) for(int g=0;g<5;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;
        for(int k=0;k<50&&!bad;k++) bad=qmvmc(sh[s].y,sh[s].x,sh[s].w,sh[s].n,sh[s].d,sh[s].mode,RGs[i],BGs[j],Gs[g],mrs[mi],t); if(p_cuCtxSynchronize()||bad) continue;
        double tt=(now()-t0)*1000/50; if(tt<best){best=tt;b0=RGs[i];b1=BGs[j];b2=Gs[g];} }
      double gbs=(double)sh[s].n/32*18*sh[s].d/(best*1e-3)/1e9;
      fprintf(stderr,"q4m%s %ux%u %s MR=%d: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\n",g_v5?"v5":"v4",sh[s].n,sh[s].d,t?"tex":"gld",mrs[mi],b0,b1,b2,best,gbs); } } }
  if(getenv("SMOL_KB_X")){ struct {unsigned n,d; CUdeviceptr w,y,x; unsigned mode;} sh[4]={{576,3072,dW[0][4],dHB,dXN,0},{1536,576,dW[0][6],dXB,dHB,2},{576,960,dW[0][0],dQKV,dXN,0},{576,576,dW[0][3],dXB,dXB2,0}};
    unsigned RGs[]={2,4,8,16}, BGs[]={1,2,3,6}, Gs[]={8,16,32}; int mrs[]={1,2,3,4,5,6,8}; int wi[4]={4,6,0,3}; int IT=2*c_nl;
    for(int s=0;s<4;s++) for(int mr=2;mr<=4;mr+=2){ unsigned rg8[]={4,8,16}, bg8[]={1,2}, g8[]={8,16,32,64}; double best=1e9; unsigned b0=0,b1=0,b2=0;
      for(int i=0;i<3;i++) for(int j=0;j<2;j++) for(int g=0;g<4;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;
        for(int k=0;k<IT&&!bad;k++) bad=qmvmc(sh[s].y,sh[s].x,dW[k%c_nl][wi[s]],sh[s].n,sh[s].d,sh[s].mode,rg8[i],bg8[j],g8[g],mr,1); if(p_cuCtxSynchronize()||bad) continue;
        double tt=(now()-t0)*1000/IT; if(tt<best){best=tt;b0=rg8[i];b1=bg8[j];b2=g8[g];} }
      fprintf(stderr,"COLD v4 MR=%d %ux%u: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\n",mr,sh[s].n,sh[s].d,b0,b1,b2,best,(double)sh[s].n/32*18*sh[s].d/(best*1e-3)/1e9); }
    for(int mi=0;mi<7;mi++){ int mr=mrs[mi]; char nm[16]; sprintf(nm,"k_q4x%d",mr); occ(nm,f_q4x[mr],64,576*4+mr*4*17*4);
      for(int s=0;s<4;s++){ double best=1e9; unsigned b0=0,b1=0,b2=0;
        for(int i=0;i<4;i++) for(int j=0;j<4;j++) for(int g=0;g<3;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;
          for(int k=0;k<IT&&!bad;k++) bad=qmvx(sh[s].y,sh[s].x,dW[k%c_nl][wi[s]],sh[s].n,sh[s].d,sh[s].mode,RGs[i],BGs[j],Gs[g],mr); if(p_cuCtxSynchronize()||bad) continue;
          double tt=(now()-t0)*1000/IT; if(tt<best){best=tt;b0=RGs[i];b1=BGs[j];b2=Gs[g];} }
        fprintf(stderr,"COLD x MR=%d %ux%u: RG=%u BG=%u G=%u thr=%u %.3f ms (%.2f GB/s)\n",mr,sh[s].n,sh[s].d,b0,b1,b2,b0*b1*8,best,(double)sh[s].n/32*18*sh[s].d/(best*1e-3)/1e9);
        if(best<1e9) occ("  best",f_q4x[mr],b0*b1*8,sh[s].n*4+mr*b0*(b1*8+1)*4); } }
    if(gpu_cls && cls_q4){ unsigned nv=nvocab; unsigned rg8[]={4,8,16}, bg8[]={1,2}, g8[]={16,64,256};
      for(int v=0;v<2;v++) for(int mr=2;mr<=(v?5:4);mr+=(v?1:2)){ double best=1e9; unsigned b0=0,b1=0,b2=0;
        for(int i=0;i<3;i++) for(int j=0;j<2;j++) for(int g=0;g<3;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;
          for(int k=0;k<3&&!bad;k++) bad= v? qmvx(dLOG,dXN,dEMB,dim,nv,0,rg8[i],bg8[j],g8[g],mr) : qmvmc(dLOG,dXN,dEMB,dim,nv,0,rg8[i],bg8[j],g8[g],mr,1); if(p_cuCtxSynchronize()||bad) continue;
          double tt=(now()-t0)*1000/3; if(tt<best){best=tt;b0=rg8[i];b1=bg8[j];b2=g8[g];} }
        fprintf(stderr,"CLSQ4 %s MR=%d: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\n",v?"x":"v4",mr,b0,b1,b2,best,(double)dim/32*18*nv/(best*1e-3)/1e9); } }
    return; }
  if(gpu_cls && !cls_q4){ unsigned RGs[]={4,8,16}, BGs[]={1,2,3}, Gs[]={64,128,256,512}; int mrs[]={2,4}; unsigned nv=nvocab;
    for(int mi=0;mi<2;mi++){ double best=1e9; unsigned b0=0,b1=0,b2=0;
      for(int i=0;i<3;i++) for(int j=0;j<3;j++) for(int g=0;g<4;g++){ p_cuCtxSynchronize(); double t0=now(); int bad=0;
        for(int k=0;k<5&&!bad;k++) bad=qmv8c(dLOG,dXN,dEMB,dim,nv,RGs[i],BGs[j],Gs[g],mrs[mi],1); if(p_cuCtxSynchronize()||bad) continue;
        double tt=(now()-t0)*1000/5; if(tt<best){best=tt;b0=RGs[i];b1=BGs[j];b2=Gs[g];} }
      fprintf(stderr,"q8m 576x%u tex MR=%d: RG=%u BG=%u G=%u %.3f ms (%.2f GB/s)\n",nv,mrs[mi],b0,b1,b2,best,(double)dim/32*34*nv/(best*1e-3)/1e9); } }
  if(getenv("SMOL_KB_ONLYNEW")) return;
  occ("k_q4f",f_q4f,64,576*4+8*324+128+256); occ("k_q4f/1536",f_q4f,192,1536*4+8*864+128+768); occ("k_q8f",f_q8f,128,576*4+8*612+128+512); occ("k_q4r",f_q4r,64,576*4+16*324+128+256); occ("k_attn_mh",f_attnmh,128,0); occ("k_rope_kv",f_ropekv,128,0);
  if(g_fused){ unsigned Rs[]={2,4,8,16,32}, Ls[]={8,16,24,32,48}, Gs[]={4,8,12,16,32,64}; struct {unsigned n,d; CUdeviceptr w,y,x,nw; unsigned mode; int q8;} sh[4]={{576,3072,dW[0][4],dHB,dX,dN[0][1],0,0},{1536,576,dW[0][6],dXB,dHB,0,2,0},{576,960,dW[0][0],dQKV,dX,dN[0][0],0,0},{576,(unsigned)nvocab,dEMB,dLOG,dX,dON,0,1}}; if(getenv("SMOL_PRENORM")){ sh[0].nw=0; sh[2].nw=0; sh[3].nw=0; }
    for(int s=0;s<4;s++){ if(s==3&&(!gpu_cls||cls_q4)) continue; double best=1e9; unsigned bR=0,bL=0,bG=0; int it=s==3?5:50;
      for(int i=0;i<5;i++) for(int j=0;j<5;j++) for(int g=0;g<6;g++){ unsigned G=Gs[g]*(s==3?4:1);
        p_cuCtxSynchronize(); double t0=now(); int bad=0; for(int k=0;k<it&&!bad;k++) bad=qmvfc(sh[s].y,sh[s].x,sh[s].w,sh[s].n,sh[s].d,sh[s].q8,sh[s].nw,sh[s].mode,Rs[i],Ls[j],G); if(p_cuCtxSynchronize()||bad) continue; double t=(now()-t0)*1000/it; if(t<best){best=t;bR=Rs[i];bL=Ls[j];bG=G;} }
      double gbs = (double)sh[s].n/32*(sh[s].q8?34:18)*sh[s].d/(best*1e-3)/1e9;
      fprintf(stderr,"fused best %ux%u%s: R=%u L=%u G=%u %.3f ms (%.2f GB/s)\n",sh[s].n,sh[s].d,sh[s].q8?" q8":"",bR,bL,bG,best,gbs); { unsigned rb=sh[s].n/32*(sh[s].q8?34:18); occ(sh[s].q8?"best q8f":"best q4f", sh[s].q8?f_q8f:f_q4f, bR*bL, sh[s].n*4+bR*rb+128+bR*bL*4); } } }
  { unsigned Rs[]={2,4,8,16}, Ls[]={8,16,24,32,48,64}, Gs[]={8,16,32,64}; struct {unsigned n,d; CUdeviceptr w,y,x; int q8;} sh[3]={{576,1536,dW[0][4],dHB,dXB,0},{1536,576,dW[0][6],dXB,dHB,0},{576,576,dW[0][0],dQ,dXB,0}};
    for(int s=0;s<3;s++){ double best=1e9; unsigned bR=0,bL=0,bG=0; unsigned rb=sh[s].n/32*18;
      for(int i=0;i<4;i++) for(int j=0;j<6;j++) for(int g=0;g<4;g++){ unsigned R=Rs[i],L=Ls[j]; if(R*L>512||R*L<32) continue; if(sh[s].n*4+R*rb+128+R*L*4>15000) continue;
        p_cuCtxSynchronize(); double a=now(); int bad=0; for(int k=0;k<50&&!bad;k++) bad=qmvc(sh[s].y,sh[s].x,sh[s].w,sh[s].n,sh[s].d,0,R,L,Gs[g]); if(p_cuCtxSynchronize()||bad) continue; double t=(now()-a)*1000/50; if(t<best){best=t;bR=R;bL=L;bG=Gs[g];} }
      fprintf(stderr,"best %ux%u: R=%u L=%u G=%u %.3f ms\n",sh[s].n,sh[s].d,bR,bL,bG,best); }
    if(gpu_cls){ int q8=!cls_q4; unsigned rb=576/32*(q8?34:18), nv=nvocab; double best=1e9; unsigned bR=0,bL=0,bG=0;
      for(int i=0;i<4;i++) for(int j=0;j<6;j++) for(int g=0;g<4;g++){ unsigned R=Rs[i],L=Ls[j],G2=Gs[g]*4; if(R*L>512||R*L<32) continue; if(576*4+R*rb+128+R*L*4>15000) continue;
        p_cuCtxSynchronize(); double a=now(); int bad=0; for(int k=0;k<10&&!bad;k++) bad=qmvc(dLOG,dX,dEMB,576,nv,q8,R,L,G2); if(p_cuCtxSynchronize()||bad) continue; double t=(now()-a)*1000/10; if(t<best){best=t;bR=R;bL=L;bG=G2;} }
      fprintf(stderr,"best classifier %s: R=%u L=%u G=%u %.3f ms\n",q8?"q8":"q4",bR,bL,bG,best); } }

  p_cuCtxSynchronize(); a=now(); for(int i=0;i<N;i++){ void* g[]={&dXB,&dX,&dN[0][0],&dim}; launch(f_rmsnorm,1,128,g);} p_cuCtxSynchronize(); fprintf(stderr,"rmsnorm %.3f ms\n",(now()-a)*1000/N);
  a=now(); for(int i=0;i<N;i++){ void* g[]={&dX,&dXB2,&dim}; launch(f_add,5,128,g);} p_cuCtxSynchronize(); fprintf(stderr,"add %.3f ms\n",(now()-a)*1000/N);
  a=now(); for(int i=0;i<N;i++) qmv(dQ,dXB,dW[0][0],dim,dim,0); p_cuCtxSynchronize(); fprintf(stderr,"q4 576x576 %.3f ms\n",(now()-a)*1000/N);
  a=now(); for(int i=0;i<N;i++) qmv(dQ,dXB,dW[0][1],dim,192,0); p_cuCtxSynchronize(); fprintf(stderr,"q4 576x192 %.3f ms\n",(now()-a)*1000/N);
  a=now(); for(int i=0;i<N;i++) qmv(dHB,dXB,dW[0][4],dim,hd,0); p_cuCtxSynchronize(); fprintf(stderr,"q4 576x1536 %.3f ms\n",(now()-a)*1000/N);
  a=now(); for(int i=0;i<N;i++) qmv(dXB,dHB,dW[0][6],hd,dim,0); p_cuCtxSynchronize(); fprintf(stderr,"q4 1536x576 %.3f ms\n",(now()-a)*1000/N);
  unsigned hs=64,T1=100,kvd=192; CUdeviceptr q=dQ,k=dKC,v=dVC,xb=dXB; a=now(); for(int i=0;i<N;i++){ void* g[]={&q,&k,&v,&xb,&hs,&T1,&kvd}; launch(f_attn_fused,1,128,g);} p_cuCtxSynchronize(); fprintf(stderr,"attn T=100 %.3f ms\n",(now()-a)*1000/N); }
/* ---- lock-free SPSC rings: producer (caller/coder thread) -> GPU worker -> producer ----
   single producer / single consumer each; head written only by producer, tail only by consumer;
   acquire/release via Interlocked + MemoryBarrier. No mutexes, no kernel waits. */
typedef struct { int id, np, ngen, ids[64], out[64], nout; double t_submit, t_done; } Req;
#define RQ 16
#ifndef FS_PAD
#define FS_PAD 1
#endif
#if FS_PAD
/* producer line: head + producer's cached copy of tail; consumer line: tail + cached head; slots on their own lines */
typedef struct __attribute__((aligned(64))) { volatile LONG head; LONG tail_c; char _p0[56]; volatile LONG tail; LONG head_c; char _p1[56]; Req* slot[RQ]; char _p2[64]; } Ring;
static int ring_push(Ring* r, Req* q){ LONG h=r->head; if(h - r->tail_c >= RQ){ r->tail_c=r->tail; if(h - r->tail_c >= RQ) return 0; } r->slot[h%RQ]=q; MemoryBarrier(); InterlockedExchange(&r->head,h+1); return 1; }
static Req* ring_pop(Ring* r){ LONG t=r->tail; if(t==r->head_c){ r->head_c=r->head; if(t==r->head_c) return 0; } MemoryBarrier(); Req* q=r->slot[t%RQ]; InterlockedExchange(&r->tail,t+1); return q; }
static int ring_empty_c(Ring* r){ if(r->tail!=r->head_c) return 0; r->head_c=r->head; return r->tail==r->head_c; }
typedef struct __attribute__((aligned(64))) { long long polls, spins, blocks, gpublocks; char _p[32]; } WStats;
typedef struct __attribute__((aligned(64))) { volatile LONG v; char _p[60]; } PadFlag;
#else
typedef struct { volatile LONG head, tail; Req* slot[RQ]; } Ring;
static int ring_empty_c(Ring* r){ return r->tail==r->head; }
typedef struct { long long polls, spins, blocks, gpublocks; } WStats;
typedef struct { volatile LONG v; } PadFlag;
#endif
#if !FS_PAD
static int ring_push(Ring* r, Req* q){ LONG h=r->head; if(h - r->tail >= RQ) return 0; r->slot[h%RQ]=q; MemoryBarrier(); InterlockedExchange(&r->head,h+1); return 1; }
static Req* ring_pop(Ring* r){ LONG t=r->tail; if(t==r->head) return 0; MemoryBarrier(); Req* q=r->slot[t%RQ]; InterlockedExchange(&r->tail,t+1); return q; }
#endif
static Ring g_in, g_out; static PadFlag g_stopf, g_wreadyf; static HANDLE g_inev; static WStats g_ws;
#define g_stop g_stopf.v
#define g_wready g_wreadyf.v
#define g_spins g_ws.spins
#define g_blocks g_ws.blocks
#define g_gpublocks g_ws.gpublocks
typedef struct { Req* r; int pos, tok; } Act;
static Req* g_rstage; static long long g_stage_n;
static int worker_work(Act* act){   /* one bounded chunk of useful work; 0 = nothing left */
  for(int i=0;i<g_inflight;i++){ Act* a=&act[i]; if(a->r && a->pos+1<a->r->np && g_seq[i].pretok!=a->r->ids[a->pos+1]) return pre_embed(&g_seq[i],a->r->ids[a->pos+1]); }
  if(!g_rstage){ Req* q=ring_pop(&g_in); if(q){ volatile int s=0; for(int j=0;j<q->np;j++) s+=q->ids[j]; q->nout=0; g_rstage=q; g_stage_n++; return 1; } }  /* drain + prefetch prompt */
  return 0; }
/* worker: owns the CUDA context. Keeps up to g_inflight requests in flight; while the GPU runs one
   request's token N, the host finishes another's token (top-K rescoring, argmax, embedding of N+1). */
static DWORD WINAPI gpu_worker(LPVOID arg){
  gpu_setup(); for(int i=0;i<2;i++) p_cuMemHostAlloc((void**)&g_pemb[i],c_dim*4,0);
  for(int i=0;i<g_inflight;i++) seq_init(&g_seq[i], i==0);
  InterlockedExchange(&g_wready,1);
  Act act[2]={{0}}; int nact=0;
  for(;;){
    for(int i=0;i<g_inflight;i++) if(!act[i].r){ Req* q=g_rstage?g_rstage:ring_pop(&g_in); g_rstage=0; if(q){ act[i].r=q; act[i].pos=0; act[i].tok=q->ids[0]; q->nout=0; enqueue_gpu(&g_seq[i],act[i].tok,0); nact++; } }
    if(!nact){ if(g_stop) break;   /* idle: short spin, then block on a Win32 event the producer signals */
      int k=0; while(k<2000 && !ring_empty_c(&g_in)==0 && !g_stop){ YieldProcessor(); k++; } g_spins+=k;
      if(ring_empty_c(&g_in) && !g_stop){ g_blocks++; WaitForSingleObject(g_inev,INFINITE); } continue; }
    int progressed=0;
    for(int i=0;i<g_inflight;i++){ Act* a=&act[i]; if(!a->r || !seq_ready(&g_seq[i])) continue; progressed=1;
      int nx=finish_gpu(&g_seq[i]); Req* q=a->r;
      if(a->pos+1<q->np) a->tok=q->ids[a->pos+1]; else { a->tok=nx; q->out[q->nout++]=nx; }
      a->pos++;
      if(q->nout>=q->ngen || a->pos>=c_ctx){ q->t_done=now(); while(!ring_push(&g_out,q)) SwitchToThread(); a->r=0; nact--; }
      else enqueue_gpu(&g_seq[i],a->tok,a->pos); }
    if(!progressed && g_waitmode==1 && worker_work(act)){ g_hs.chunks++; continue; }
    if(!progressed && g_waitmode==2){ YieldProcessor(); continue; }
    if(!progressed){ /* GPU busy: spin a little, then sleep in the driver on the oldest in-flight event */
      g_polls++; if(g_polls % 64 == 0){ for(int i=0;i<g_inflight;i++) if(act[i].r){ g_gpublocks++; p_cuEventSynchronize(g_seq[i].ev); break; } } else YieldProcessor(); } }
  return 0; }
static int serve(char** lists, int nl, int ngen, int inflight){
  g_inflight=inflight; g_inev=CreateEventA(0,FALSE,FALSE,0); HANDLE th=CreateThread(0,0,gpu_worker,0,0,0); while(!g_wready) SwitchToThread();
  Req* rq=calloc(nl,sizeof(Req)); double t0=now(); int ntok=0;
  for(int i=0;i<nl;i++){ char* s=lists[i]; rq[i].id=i; rq[i].ngen=ngen; while(*s){ rq[i].ids[rq[i].np++]=strtol(s,&s,10); while(*s==','||*s==' ') s++; } rq[i].t_submit=now(); while(!ring_push(&g_in,&rq[i])) SwitchToThread(); SetEvent(g_inev); }
  for(int got=0; got<nl;){ Req* q=ring_pop(&g_out); if(!q){ SwitchToThread(); continue; } got++; ntok+=q->nout+q->np-1; }
  double dt=now()-t0; g_stop=1; SetEvent(g_inev); WaitForSingleObject(th,INFINITE);
  printf("serve inflight=%d requests=%d forward_tokens=%d wall=%.2fs -> %.2f tok/s (gen %d/req), host polls %lld, gpu blocking waits %lld, idle spins %lld, idle blocks %lld, wait mode %d work chunks %lld prehits %lld staged %lld\n",inflight,nl,ntok,dt,ntok/dt,ngen,g_polls,g_gpublocks,g_spins,g_blocks,g_waitmode,g_hs.chunks,g_hs.prehits,g_stage_n);
  for(int i=0;i<nl;i++){ printf("req%d_ids=",i); for(int j=0;j<rq[i].nout;j++) printf("%d,",rq[i].out[j]); printf("\n"); }
  return 0; }
/* GPT-2 byte-level decode */
static int u2b[512];
static void initdec(void){ int n=0; for(int b=0;b<256;b++){ int keep=(b>=33&&b<=126)||(b>=161&&b<=172)||(b>=174&&b<=255); if(keep) u2b[b]=b; } 
  for(int b=0;b<256;b++){ int keep=(b>=33&&b<=126)||(b>=161&&b<=172)||(b>=174&&b<=255); if(!keep){ u2b[256+n]=b; n++; } } }
static void dec(const char* s, FILE* o){ const unsigned char* p=(const unsigned char*)s; while(*p){ int cp; if(*p<0x80) cp=*p++; else if((*p&0xE0)==0xC0){ cp=((p[0]&31)<<6)|(p[1]&63); p+=2; } else { cp=((p[0]&15)<<12)|((p[1]&63)<<6)|(p[2]&63); p+=3; }
  if(cp<512) fputc(u2b[cp],o); } }
static double now(void){ LARGE_INTEGER f,c; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&c); return (double)c.QuadPart/f.QuadPart; }
static int run(int gpu,int* pr,int np,int ngen,int* out){
  int tok=pr[0], pos=0, n=0; double t0=0;
  for(;pos<np+ngen-1 && pos<c_ctx;pos++){
    if(pos==np) t0=now();
    int nx;
    if(gpu) nx=fwd_gpu_tok2(tok,pos,pos+1<np?pr[pos+1]:-1); else { fwd_cpu(tok,pos); nx=0; for(int i=1;i<nvocab;i++) if(LOG[i]>LOG[nx]) nx=i; }
    if(pos+1<np) tok=pr[pos+1]; else { tok=nx; out[n++]=tok; }
  }
  double dt=now()-t0; fprintf(stderr,"[%s] %d tokens, decode %.2f tok/s\n",gpu?"gpu":"cpu",n,(n-1)/dt);
  printf("%s_tps=%.2f\n",gpu?"gpu":"cpu",(n-1)/dt); if(gpu) printf("wait mode=%d tok_lat avg %.2f ms max %.2f ms, work chunks %lld, prehits %lld, spins %lld, blocks %lld\n",g_waitmode,g_hs.lat_sum/(g_hs.nwait?g_hs.nwait:1),g_hs.lat_max,g_hs.chunks,g_hs.prehits,g_hs.spins,g_hs.blocks);
  if(gpu) fprintf(stderr,"cpu classifier %.1f ms/tok of %.1f\n",t_cls*1000/(np+n-1),dt*1000/(n-1));
  return n; }
int main(int argc,char** argv){
  if(argc<4){fprintf(stderr,"usage\n");return 1;}
  load(argv[1]); initdec(); if(getenv("SMOL_WAIT")) g_waitmode=atoi(getenv("SMOL_WAIT")); if(getenv("SMOL_CTX")) c_ctx=atoi(getenv("SMOL_CTX")); if(c_ctx>128) c_ctx=128;
  int pr[128],np=0; char* s=argv[2]; while(*s){ pr[np++]=strtol(s,&s,10); while(*s==','||*s==' '||*s==';') s++; }
  int ngen=atoi(argv[3]); const char* mode=argc>4?argv[4]:"both";
  int hs=c_dim/c_nh, kvd=hs*c_nkv;
  ccos=malloc(c_ctx*hs/2*4); csin=malloc(c_ctx*hs/2*4);
  for(int p=0;p<c_ctx;p++) for(int j=0;j<hs/2;j++){ double fr=pow(c_base,-2.0*j/hs); ccos[p*(hs/2)+j]=(float)cos(p*fr); csin[p*(hs/2)+j]=(float)sin(p*fr); }
  kc=calloc((size_t)c_nl*c_ctx*kvd,4); vc=calloc((size_t)c_nl*c_ctx*kvd,4);
  X=malloc(c_dim*4);XB=malloc(c_dim*4);XB2=malloc(c_dim*4);Q=malloc(c_dim*4);HB=malloc(c_hd*4);HB2=malloc(c_hd*4);ATT=malloc(c_ctx*4);LOG=malloc((size_t)nvocab*4);
  int og[128],oc[128],ng=0,nc=0;
  if(!strcmp(mode,"serve")){ char* lists[16]; int nl=0; char* s2=strdup(argv[2]); for(char* t=strtok(s2,";");t&&nl<16;t=strtok(0,";")) lists[nl++]=t; return serve(lists,nl,ngen,argc>5?atoi(argv[5]):2); }
  if(strcmp(mode,"cpu")){ gpu_setup(); for(int i=0;i<2;i++) p_cuMemHostAlloc((void**)&g_pemb[i],c_dim*4,0); seq_init(&g_seq[0],1); if(getenv("SMOL_KBENCH")) kbench(); ng=run(1,pr,np,ngen,og); printf("gpu_ids="); for(int i=0;i<ng;i++) printf("%d,",og[i]); printf("\ngpu_text="); for(int i=0;i<ng;i++) dec(vocab[og[i]],stdout); printf("\n"); }
  if(strcmp(mode,"gpu")){ nc=run(0,pr,np,ngen,oc); printf("cpu_ids="); for(int i=0;i<nc;i++) printf("%d,",oc[i]); printf("\ncpu_text="); for(int i=0;i<nc;i++) dec(vocab[oc[i]],stdout); printf("\n"); }
  if(ng&&nc){ int m=0; while(m<ng&&m<nc&&og[m]==oc[m]) m++; printf("match_prefix=%d/%d\n",m,ng); }
  return 0; }
