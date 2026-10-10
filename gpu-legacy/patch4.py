import sys
p=sys.argv[1]; s=open(p,encoding='utf-8').read()
def rep(a,b):
    global s
    assert a in s, a[:60]; s=s.replace(a,b,1)
rep("static CUfunction f_q4m[2][3];","static CUfunction f_q4m[2][3], f_q4v[2][3]; static int g_v5=1;")
rep("unsigned T=RG*BG*8; if(T>512||T<32||(n/32)%BG||d%mr) return 1; unsigned sm=n*4+T*mr*4;",
    "unsigned T=RG*BG*8; if(T>512||T<32||(n/32)%BG||d%mr||(g_v5&&RG*mr>T)) return 1; unsigned sm=g_v5? n*4+mr*RG*(BG*8+1)*4 : n*4+T*mr*4;")
rep("return p_cuLaunchKernel(f_q4m[tex][MRI(mr)],","return p_cuLaunchKernel((g_v5?f_q4v:f_q4m)[tex][MRI(mr)],")
rep('for(int t=0;t<2;t++) for(int m=0;m<3;m++) if(p_cuModuleGetFunction(&f_q4m[t][m],g_sm11_mod,nm[t][m])) ok=0;',
    'for(int t=0;t<2;t++) for(int m=0;m<3;m++){ char v[16]; sprintf(v,"k_q4v%s",nm[t][m]+4); if(p_cuModuleGetFunction(&f_q4m[t][m],g_sm11_mod,nm[t][m])||p_cuModuleGetFunction(&f_q4v[t][m],g_sm11_mod,v)) ok=0; }\n    if(getenv("SMOL_V5")) g_v5=atoi(getenv("SMOL_V5"));')
rep('fprintf(stderr,"q4m %ux%u %s MR=%d:','fprintf(stderr,"q4m%s %ux%u %s MR=%d:",g_v5?"v5":"v4",')
s=s.replace('"q4m%s %ux%u %s MR=%d:",g_v5?"v5":"v4", RG=%u','"q4m%s %ux%u %s MR=%d: RG=%u',1)
# --- false sharing: rings + stats ---
rep("typedef struct { volatile LONG head, tail; Req* slot[RQ]; } Ring;",
r'''#ifndef FS_PAD
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
#endif''')
rep("static int ring_push(Ring* r, Req* q){ LONG h=r->head; if(h - r->tail >= RQ) return 0;","#if !FS_PAD\nstatic int ring_push(Ring* r, Req* q){ LONG h=r->head; if(h - r->tail >= RQ) return 0;")
rep("InterlockedExchange(&r->tail,t+1); return q; }\nstatic Ring g_in","InterlockedExchange(&r->tail,t+1); return q; }\n#endif\nstatic Ring g_in")
rep("static Ring g_in, g_out; static volatile LONG g_stop, g_wready; static HANDLE g_inev; static long long g_spins, g_blocks, g_gpublocks;",
    "static Ring g_in, g_out; static PadFlag g_stopf, g_wreadyf; static HANDLE g_inev; static WStats g_ws;\n#define g_stop g_stopf.v\n#define g_wready g_wreadyf.v\n#define g_spins g_ws.spins\n#define g_blocks g_ws.blocks\n#define g_gpublocks g_ws.gpublocks")
rep("g_in.tail==g_in.head && !g_stop){ YieldProcessor();","!ring_empty_c(&g_in)==0 && !g_stop){ YieldProcessor();")
rep("if(g_in.tail==g_in.head && !g_stop){ g_blocks++;","if(ring_empty_c(&g_in) && !g_stop){ g_blocks++;")
rep('static long long g_polls;','#if !defined(FS_PAD) || FS_PAD\nstatic long long g_polls __attribute__((aligned(64))); static char g_polls_pad[56] __attribute__((unused));\n#else\nstatic long long g_polls;\n#endif')
open(p,'w',encoding='utf-8').write(s); print("ok")
