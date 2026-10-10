# k_q4{t|g}{MR}: register-blocked multi-row Q4_0 matvec; weights via texture (t) or plain global (g);
# x cached in smem once per CTA (optionally silu(g)*u), MR rows per thread share every x load.
def kern(MR, tex):
    name = f"k_q8{'t' if tex else 'g'}{MR}"
    def fetch(dst, wordreg):
        if tex:
            return f"  tex.1d.v4.u32.s32 {{{dst}, %r90, %r91, %r92}}, [tw_q4, {{{wordreg}}}];\n"
        return f"  mul.wide.u32 %rd30, {wordreg}, 4; add.u64 %rd30, %rd3, %rd30; ld.global.u32 {dst}, [%rd30];\n"
    body = ""
    for m in range(MR):
        body += f"""  mad.lo.u32 %r61, %r9, {m}, %r60;
  shr.u32 %r62, %r61, 2; add.u32 %r62, %r62, %r3;
{fetch('%r63','%r62')}  and.b32 %r64, %r61, 2; shl.b32 %r64, %r64, 3; shr.u32 %r63, %r63, %r64;
  cvt.u16.u32 %h1, %r63; cvt.f32.f16 %f20, %h1;
  add.u32 %r65, %r61, %r42; shr.u32 %r66, %r65, 2; add.u32 %r66, %r66, %r3;
{fetch('%r67','%r66')}  and.b32 %r68, %r65, 2; setp.eq.u32 %p9, %r68, 0; @%p9 bra AL{m};
  add.u32 %r66, %r66, 1;
{fetch('%r69','%r66')}  shr.u32 %r67, %r67, 16; shl.b32 %r69, %r69, 16; or.b32 %r67, %r67, %r69;
AL{m}:
  shl.b32 %r69, %r67, 24; shr.s32 %r69, %r69, 24; cvt.rn.f32.s32 %f21, %r69; mul.f32 %f22, %f21, %f10;
  shl.b32 %r69, %r67, 16; shr.s32 %r69, %r69, 24; cvt.rn.f32.s32 %f21, %r69; mad.f32 %f22, %f21, %f11, %f22;
  shl.b32 %r69, %r67, 8; shr.s32 %r69, %r69, 24; cvt.rn.f32.s32 %f21, %r69; mad.f32 %f22, %f21, %f12, %f22;
  shr.s32 %r69, %r67, 24; cvt.rn.f32.s32 %f21, %r69; mad.f32 %f22, %f21, %f13, %f22;
  mad.f32 %f{30+m}, %f22, %f20, %f{30+m};
"""
    red_st = "".join(f"  st.shared.f32 [%rd12+{4*m}], %f{30+m};\n" for m in range(MR))
    zero = "".join(f"  mov.f32 %f{30+m}, 0f00000000;\n" for m in range(MR))
    sums = ""
    for m in range(MR):
        sums += f"""  mov.f32 %f40, 0f00000000; mov.u32 %r35, 0;
SL{m}: setp.ge.u32 %p8, %r35, %r5; @%p8 bra SLD{m};
  mul.lo.u32 %r36, %r35, {4*MR}; cvt.u64.u32 %rd13, %r36; add.u64 %rd13, %rd12, %rd13; ld.shared.f32 %f41, [%rd13+{4*m}]; add.f32 %f40, %f40, %f41;
  add.u32 %r35, %r35, 1; bra SL{m};
SLD{m}: add.u32 %r37, %r28, {m}; mul.wide.u32 %rd14, %r37, 4; add.u64 %rd14, %rd1, %rd14;
  @%p10 ld.global.f32 %f41, [%rd14]; @%p10 add.f32 %f40, %f40, %f41;
  st.global.f32 [%rd14], %f40;
"""
    return f"""
.visible .entry {name}(.param .u64 py, .param .u64 px, .param .u64 pw, .param .u32 pwoff, .param .u32 pn, .param .u32 pd,
                       .param .u32 pRG, .param .u32 pBG, .param .u32 pmode)
{{
  .reg .u32 %r<100>; .reg .u64 %rd<32>; .reg .f32 %f<48>; .reg .pred %p<12>; .reg .b16 %h<4>;
  ld.param.u64 %rd1, [py]; ld.param.u64 %rd2, [px]; ld.param.u64 %rd3, [pw]; ld.param.u32 %r3, [pwoff];
  ld.param.u32 %r1, [pn]; ld.param.u32 %r2, [pd]; ld.param.u32 %r70, [pRG]; ld.param.u32 %r71, [pBG]; ld.param.u32 %r45, [pmode];
  mov.u32 %r41, %ntid.x; mov.u32 %r4, %tid.x;
  shl.b32 %r5, %r71, 3;                      // L = 8*BG lanes per row group
  rem.u32 %r6, %r4, %r5; div.u32 %r7, %r4, %r5;   // lane, row group
  and.b32 %r72, %r6, 7; shr.u32 %r43, %r6, 3;      // k (u16 slot), block group
  shl.b32 %r42, %r72, 2; add.u32 %r42, %r42, 2;    // byte offset of this lane's u16 inside a block
  shr.u32 %r8, %r1, 5; mul.lo.u32 %r9, %r8, 34;   // nb, row bytes
  mov.u64 %rd4, dsm_q;
  shl.b32 %r10, %r1, 2; cvt.u64.u32 %rd5, %r10; add.u64 %rd6, %rd4, %rd5;   // red after x
  // x prologue (bit1: silu(x)*x[n+i])
  and.b32 %r46, %r45, 2; and.b32 %r47, %r45, 1; setp.ne.u32 %p10, %r47, 0;
  mov.u32 %r25, %r4;
XL: setp.ge.u32 %p1, %r25, %r1; @%p1 bra XLD;
  mul.wide.u32 %rd7, %r25, 4; add.u64 %rd8, %rd2, %rd7; ld.global.f32 %f5, [%rd8];
  setp.eq.u32 %p3, %r46, 0; @%p3 bra XNS;
  add.u64 %rd9, %rd8, %rd5; ld.global.f32 %f6, [%rd9];
  mul.f32 %f7, %f5, 0fbfb8aa3b; ex2.approx.f32 %f7, %f7; add.f32 %f7, %f7, 0f3f800000; div.approx.f32 %f5, %f5, %f7; mul.f32 %f5, %f5, %f6;
XNS: add.u64 %rd8, %rd4, %rd7; st.shared.f32 [%rd8], %f5; add.u32 %r25, %r25, %r41; bra XL;
XLD: bar.sync 0;
  mul.wide.u32 %rd12, %r4, {4*MR}; add.u64 %rd12, %rd6, %rd12;
  mov.u32 %r15, %ctaid.x; mov.u32 %r16, %nctaid.x;
  mul.lo.u32 %r73, %r70, {MR};                 // rows per CTA iteration
  mul.lo.u32 %r17, %r15, %r73; mul.lo.u32 %r18, %r16, %r73;
CHUNK:
  setp.ge.u32 %p1, %r17, %r2; @%p1 bra DONE;
  mad.lo.u32 %r28, %r7, {MR}, %r17;            // first row of this thread
  setp.lt.u32 %p4, %r28, %r2;
{zero}  @!%p4 bra RED;
  mul.lo.u32 %r74, %r28, %r9;                  // byte offset of row
  mov.u32 %r30, %r43;
BL: setp.ge.u32 %p5, %r30, %r8; @%p5 bra RED;
  // x for elems b*32+2k, +1, +16, +17 (shared by all MR rows)
  shl.b32 %r33, %r30, 5; add.u32 %r33, %r33, %r42; sub.u32 %r33, %r33, 2; shl.b32 %r33, %r33, 2; cvt.u64.u32 %rd11, %r33; add.u64 %rd11, %rd4, %rd11;
  ld.shared.f32 %f10, [%rd11]; ld.shared.f32 %f11, [%rd11+4]; ld.shared.f32 %f12, [%rd11+8]; ld.shared.f32 %f13, [%rd11+12];
  mad.lo.u32 %r60, %r30, 34, %r74;            // block byte offset in row m=0
{body}  add.u32 %r30, %r30, %r71; bra BL;
RED:
{red_st}  bar.sync 0;
  setp.ne.u32 %p6, %r6, 0; @%p6 bra NEXT; @!%p4 bra NEXT;
{sums}NEXT: bar.sync 0; add.u32 %r17, %r17, %r18; bra CHUNK;
DONE: ret;
}}
"""
src = "\n// ---- v4 register-blocked multi-row Q8 classifier (tex/global) ----\n"
for tex in (1, 0):
    for MR in (2, 4):
        src += kern(MR, tex)
open("rows5.ptx", "w").write(src)
