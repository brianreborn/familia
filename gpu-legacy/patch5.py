import sys,re
p=sys.argv[1]; s=open(p,encoding='utf-8').read()
def rep(a,b,cnt=1):
    global s
    assert a in s, a[:70]; s=s.replace(a,b,cnt)
# Seq gets per-seq double-buffered pinned embedding + pre-embed tag + enqueue timestamp
s,n=re.subn(r"\}\s*Seq;", " float* pe[2]; int pei, pretok; double t_enq; } Seq;", s, 1); assert n==1
rep("q->inflight=0; }", "q->inflight=0; for(int i=0;i<2;i++) if(p_cuMemHostAlloc((void**)&q->pe[i],c_dim*4,0)){fprintf(stderr,\"pinned alloc failed\\n\");exit(3);} q->pei=0; q->pretok=-1; }")
rep("float* pe=g_pemb[g_pembi^=1]; embed(pe,tok);",
    "sq->pei^=1; float* pe=sq->pe[sq->pei]; if(sq->pretok!=tok) embed(pe,tok); else g_hs.prehits++; sq->pretok=-1;")
rep("CKL(p_cuEventRecord(sq->ev,0)); sq->inflight=1;", "CKL(p_cuEventRecord(sq->ev,0)); sq->t_enq=now(); sq->inflight=1;")
# host-side stats (own cache line) + wait-with-work
rep("static float* g_pemb[2];", r'''static int g_waitmode=1; /* 0: spin64+block (old)  1: bounded useful work, then spin64, then block  2: pure spin (latency floor) */
static struct __attribute__((aligned(64))) { long long chunks, spins, blocks, prehits, nwait; double lat_sum, lat_max; char _p[8]; } g_hs;
static float* g_pemb[2];''')
rep("static int seq_ready(Seq* q){", r'''typedef int (*WorkFn)(void*);
/* pre-embed the next (already known) token into this seq's free pinned buffer: the buffer last used by token N-1, whose H2D is complete */
static int pre_embed(Seq* q, int tok){ if(q->pretok==tok) return 0; embed(q->pe[q->pei^1],tok); q->pretok=tok; return 1; }
static int seq_ready(Seq* q){''')
rep("static void seq_wait(Seq* q){ for(int k=0;k<64;k++){ if(seq_ready(q)) return; g_polls++; YieldProcessor(); } p_cuEventSynchronize(q->ev); }",
r'''static void seq_wait_w(Seq* q, WorkFn fn, void* ctx){
  if(g_waitmode==2){ while(!seq_ready(q)) YieldProcessor(); goto done; }
  if(g_waitmode==1 && fn){ while(fn(ctx)){ g_hs.chunks++; if(seq_ready(q)) goto done; } }   /* each chunk ~10-50 us */
  for(int k=0;k<64;k++){ if(seq_ready(q)) goto done; g_hs.spins++; YieldProcessor(); }
  g_hs.blocks++; p_cuEventSynchronize(q->ev);
done: { double l=(now()-q->t_enq)*1000; g_hs.lat_sum+=l; if(l>g_hs.lat_max) g_hs.lat_max=l; g_hs.nwait++; } }
static void seq_wait(Seq* q){ seq_wait_w(q,0,0); }''')
# run(): pre-embed next prompt token while token N runs
rep("static int fwd_gpu_tok(int tok,int pos){ Seq* q=&g_seq[0]; enqueue_gpu(q,tok,pos); seq_wait(q); return finish_gpu(q); }",
r'''typedef struct { Seq* q; int next; } RunW;
static int run_work(void* c){ RunW* w=c; if(w->next<0) return 0; int t=w->next; w->next=-1; return pre_embed(w->q,t); }
static int fwd_gpu_tok2(int tok,int pos,int next){ Seq* q=&g_seq[0]; enqueue_gpu(q,tok,pos); RunW w={q,next}; seq_wait_w(q,run_work,&w); return finish_gpu(q); }
static int fwd_gpu_tok(int tok,int pos){ return fwd_gpu_tok2(tok,pos,-1); }''')
rep("if(gpu) nx=fwd_gpu_tok(tok,pos);", "if(gpu) nx=fwd_gpu_tok2(tok,pos,pos+1<np?pr[pos+1]:-1);")
rep('if(gpu) fprintf(stderr,"cpu classifier', r'''if(gpu) printf("wait mode=%d tok_lat avg %.2f ms max %.2f ms, work chunks %lld, prehits %lld, spins %lld, blocks %lld\n",g_waitmode,g_hs.lat_sum/(g_hs.nwait?g_hs.nwait:1),g_hs.lat_max,g_hs.chunks,g_hs.prehits,g_hs.spins,g_hs.blocks);
  if(gpu) fprintf(stderr,"cpu classifier''')
# serve worker: staging of next request + pre-embed of next prompt tokens as bounded work
rep("typedef struct { Req* r; int pos, tok; } Act;", r'''typedef struct { Req* r; int pos, tok; } Act;
static Req* g_stage; static long long g_stage_n;
static int worker_work(Act* act){   /* one bounded chunk of useful work; 0 = nothing left */
  for(int i=0;i<g_inflight;i++){ Act* a=&act[i]; if(a->r && a->pos+1<a->r->np && g_seq[i].pretok!=a->r->ids[a->pos+1]) return pre_embed(&g_seq[i],a->r->ids[a->pos+1]); }
  if(!g_stage){ Req* q=ring_pop(&g_in); if(q){ volatile int s=0; for(int j=0;j<q->np;j++) s+=q->ids[j]; q->nout=0; g_stage=q; g_stage_n++; return 1; } }  /* drain + prefetch prompt */
  return 0; }''')
rep("Req* q=ring_pop(&g_in); if(q){ act[i].r=q;", "Req* q=g_stage?g_stage:ring_pop(&g_in); g_stage=0; if(q){ act[i].r=q;")
rep("    if(!progressed){ /* GPU busy", "    if(!progressed && g_waitmode==1 && worker_work(act)){ g_hs.chunks++; continue; }\n    if(!progressed && g_waitmode==2){ YieldProcessor(); continue; }\n    if(!progressed){ /* GPU busy")
rep('idle spins %lld, idle blocks %lld\\n",inflight,nl,ntok,dt,ntok/dt,ngen,g_polls,g_gpublocks,g_spins,g_blocks);',
    'idle spins %lld, idle blocks %lld, wait mode %d work chunks %lld prehits %lld staged %lld\\n",inflight,nl,ntok,dt,ntok/dt,ngen,g_polls,g_gpublocks,g_spins,g_blocks,g_waitmode,g_hs.chunks,g_hs.prehits,g_stage_n);')
rep("load(argv[1]); initdec();", "load(argv[1]); initdec(); if(getenv(\"SMOL_WAIT\")) g_waitmode=atoi(getenv(\"SMOL_WAIT\"));")
open(p,'w',encoding='utf-8').write(s); print("ok")
