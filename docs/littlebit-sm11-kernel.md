# LittleBit on sm_11 (GeForce 8600 GT): fused sign-matmul kernel spec

Handoff to the qodesh legacy-GPU work (`feat/qodesh-legacy-gpu`, not edited here). It follows the rules
already in that branch's LESSONS-LEARNED: **no host sync per op, at most one wait per token, one VRAM
arena, a 16 MiB margin, refuse to load rather than eat into the margin.** Nothing here has run on the GPU yet.
The throughput numbers are estimates and are labeled as such.

## The layer

For one token (GEMV), with `x` ∈ ℝ^a and signs S_V (r×a) and S_U (b×r):

```
s = x ⊙ v2                     (a)       column scale
t = (S_V · s) ⊙ (v1 ⊙ u2)      (r)       stage A: r sign-dots of length a
y = (S_U · t) ⊙ u1             (b)       stage B: b sign-dots of length r
(+ the same again with *_R when littlebit.residual, + bias)
```

A sign-dot over packed bits needs no multiplies and no popcount, because activations stay float:
`dot(s, sign row) = Σ s_i − 2·Σ_{bit_i = 1} s_i`. Precompute `Σ s` once per stage, then each word
adds the elements whose bit is set (branch-free: `acc += s_i * (float)((w >> i) & 1)`, or `fsel`).
Fold `v1⊙u2` into one vector at load time (exact in f32 up to rounding; record it in the self-test).

## Kernel design (cc 1.1 limits: 16 KiB shared, 8192 regs/SM, ≤512 threads/block, 32-bit global atomics only, no shuffles, no shared atomics)

1. **Load-time repack** (host, once): pad every packed row to a multiple of 16 words (64 B) so that a half-warp
   reading consecutive words is one coalesced segment on cc1.1. Fuse `v1⊙u2` → `lat`. Put all of a layer's
   tensors in the existing arena. The file format (format_version 1) does not change; this is an in-VRAM layout.
2. **k_lb_stageA** (one launch per LittleBit linear, or **one launch for q,k,v together**, since they share `x`):
   - grid = ⌈r_total / 16⌉ blocks of 128 threads; the block stages `s = x⊙v2` (and `Σs`) in shared memory.
     If a·4 B > ~12 KiB (ffn_down: a = 5120 → 20 KiB) it tiles `s` in 2–3 chunks or reads `s` via
     `tex1Dfetch` (the texture cache works on cc1.1).
   - each half-warp owns one output row r_j and strides over its words; partial sums are reduced in shared
     memory with a fixed tree (no atomics), then `t_j = (Σs − 2·acc)·lat_j`.
3. **k_lb_stageB**: same shape with `t` (r ≤ 1160 floats, fits in shared) as the input, b rows, `·u1`, an optional
   fused residual add, and the next op's epilogue (residual stream add / SiLU·up) where it is cheap.
4. **Ordering, not syncing**: stage B depends on stage A only through stream order, so the host enqueues
   A, B, A, B, … for the whole forward pass and waits once per token on the existing event-poll path.
   Ring buffers for CPU↔GPU handoff stay as specified in SYNC-AUDIT.md.
5. `__popc` is not needed. If an alternative ±1-activation variant is ever tried, verify `__popc` codegen on
   sm_11 first.

## VRAM plan (estimates from upstream's rank rule, see littlebit.md)

| model | LittleBit linears | scales (F32) | embed / head | fits 8600 GT (72–154 MiB free − 16 margin)? |
|---|---|---|---|---|
| stories15M QAT eff 0.1 (have it) | 0.16 MiB | incl. | 35 + 35 MiB F32 (Q4_0: ~5 + 5) | yes |
| K2-Horizon-0.9B eff 0.1 (not trained) | ~11.6 MiB | incl. | 188 MiB f16 each; Q4_0 ≈ 53 MiB head, embed gather on CPU | head Q4_0 + layers ≈ 65 MiB + KV: only at the high end of free VRAM; otherwise head on CPU |
| K2-Horizon-0.9B eff 0.55 | ~60 MiB | incl. | as above | layers only; head on CPU |

The **LM head, not the LittleBit layers,** is what limits fit and bandwidth: at 0.1 bpw K2-Horizon reads
about 11.6 MiB of signs per token, but about 53 MiB for a Q4_0 head. Keep the head on the existing Q4 kernel (`k_q4r`).

Rough compute estimate for K2-Horizon eff 0.1 (not measured): about 68 M sign-adds per token → about 0.25 G simple
ops with bit extraction. On 32 SPs at 1.19 GHz that's ~7 ms, plus ~0.5 ms of sign reads and ~2.4 ms of Q4 head
reads at ~22 GB/s. **Ceiling: ~100 tok/s before launch overhead (~2×28×7 launches ≈ 4 ms)**, so realistically
tens of tok/s. Only a real run decides this.

## Acceptance tests (golden data from the CPU reference, committed)

`tests/fixtures/littlebit/s15m-qat-{0.1,1.0}.lbit.gguf.golden.json` holds the sha256 of the `.lbit.gguf`, the prompt ids,
the top-10 of the last logits and its first 8 values, 16 greedy tokens, and `blk.0.attn_q` output for
`x = linspace(-1, 1, 288)`. Regenerate the files on any box:

```
python produce_tiny.py --gguf stories15M.gguf --upstream LittleBit --out ck --eff-bit 0.1 --use-itq --qat-steps 300 --lr 2e-3 --threads 4
python convert.py --checkpoint ck --base-gguf stories15M.gguf --out s15m-qat-0.1.lbit.gguf
```

(Seeded, but torch thread scheduling can change the last bits. Compare against the golden sha256 when you copy
the file and against the tolerance otherwise.) Pass criteria for the GPU path:

- the single-layer output is within 1e-4 relative of the golden values;
- last-token argmax and top-10 are identical;
- greedy 16 tokens are identical;
- exactly 1 host wait per token, counted by the existing sync audit;
- tok/s alone and alongside the CPU coder, reported against the 34 tok/s dense-stories15M baseline.
