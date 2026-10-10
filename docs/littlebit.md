# LittleBit in familia (issue #28)

Status: **research done; format, converter, CPU reference runtime and `scale_down.py --method littlebit`
work end to end on a tiny model.** No serving runtime yet (llama.cpp cannot load LittleBit), no GPU kernel yet
(spec: [littlebit-sm11-kernel.md](littlebit-sm11-kernel.md)), no real QAT run (needs a CUDA GPU; HF credits, #36).

## M1 research (checked 2026-10-09)

| item | finding |
|---|---|
| paper | Lee, Kim, You, Kim, *LittleBit: Ultra Low-Bit Quantization via Latent Factorization*, NeurIPS 2025, arXiv [2506.13771](https://arxiv.org/abs/2506.13771). Follow-up: Lee & Kim, *LittleBit-2* (ICML 2026): Joint-ITQ latent rotation at init only, same deployed layer. |
| official code | [SamsungLabs/LittleBit](https://github.com/SamsungLabs/LittleBit) (inspected at `42d658b`). PyTorch + transformers + DeepSpeed; train `main.py`, eval `eval.py`, HF hub mixin `quantization/hub.py`. |
| license | **CC BY-NC 4.0** (non-commercial). familia does not vendor any of it: `produce_tiny.py` and `check_ref.py` import a checkout you point them at (`--upstream`). The familia format, converter and runtime are independent code written from the published format. |
| official checkpoints | **None** released by Samsung. README examples use a placeholder `username/littlebit-llama-7b-0.1bpw`. |
| K2-Horizon-0.9B | Base model exists ([IFM/K2-Horizon-0.9B](https://huggingface.co/IFM/K2-Horizon-0.9B), custom `k2_horizon` arch, remote code, yarn rope, 28 layers, hidden 1536, vocab 64256, untied head). **No LittleBit version exists.** |
| community | `tmt-ai-corp/LittleSpec` (fork + llama.cpp CPU speculative-decoding draft at 0.1 bpw via a private llama.cpp fork, not public); `kimwin2/lb_kernels` (CUDA packed-sign GEMV + CPU fused linear, no llama.cpp fork); HF `Haverbex/Qwen3.8-27B-LittleBit-*` (uploaded 2026-10-09, unverified, 27B: irrelevant to our hardware); `LittleBitLLM/*` + littlebitllm.com (the "littlebit-qwen3-4b" GGUFs are **ordinary Q4/Q5/Q8**, not sub-1-bit; the site advertises a crypto token; treat as unaffiliated). |
| compute for QAT | Paper recipe: 5 epochs KD on C4+WikiText2, bs 4/GPU, lr 4e-5, SmoothSign, residual, `l2l_loss_scale 10`, CUDA (DeepSpeed ZeRO-3 for multi-GPU), transformers 4.51. A community report puts Qwen3-8B at 2.84 s/step, ~16.5 h per epoch on their GPUs. Nothing in familia's fleet can do this for 0.9B+; HF Jobs could, once the account has credits. |

### Weight format (upstream, exact)

Per `nn.Linear` (all except `lm_head`; embeddings stay dense) with in=a, out=b, rank r:

- `U` (b×r) and `V` (r×a) signs, stored as `<layer>.U_packed`/`.V_packed`: int32, row-major, **LSB first, bit 1 = −1**, rows padded with +1 to 32; plus `<layer>.U_shape`/`.V_shape` (int64).
- scales `u1` (1×b), `u2` (1×r), `v1` (1×r), `v2` (1×a), bf16/fp32. With `residual`, a second set `*_R`.
- forward: `y = ((((x ⊙ v2) · sign(V)ᵀ) ⊙ (v1 ⊙ u2)) · sign(U)ᵀ) ⊙ u1` (+ residual path, + bias).
- r is picked from `eff_bit`: `r = ⌊(a·b·eff − 16(a+b)) / (a+b+16)⌋₈`, min 8 (`kv_factor` scales k/v). Upstream counts scales as 16-bit.
- Checkpoint dir: `model.safetensors` (or sharded + index), `config.json`, `littlebit_config.json`.

## M2 familia format: `.lbit.gguf` (format_version 1)

A normal GGUF v3 that keeps the source's `general.architecture` and tokenizer KVs, with each factorized
`<t>.weight` replaced by `<t>.lb.{U,V}` (I32, packed exactly like upstream, so conversion copies words) and
`<t>.lb.{u1,u2,v1,v2}` (F32), `<t>.lbr.*` for residual. KVs: `familia.quant=littlebit`,
`littlebit.format_version=1`, `littlebit.sign_packing`, `littlebit.residual`, `littlebit.eff_bit_target`,
`littlebit.upstream_config` (JSON), `familia.provenance`. Standard ggml types only, no custom type id:
llama.cpp opens the header but refuses the model (missing `.weight`), and familia's validator refuses
any runtime that doesn't declare `quants: [littlebit]`. q/k rows are permuted into llama.cpp's rope
layout at conversion time; since that is a row permutation, whole packed rows of U and u1 move, with no repacking.

Tools (`scripts/littlebit/`): `lbformat.py` (pack/unpack, bit layout; matches upstream `binary_packer`
bit-for-bit), `convert.py` (upstream checkpoint + base GGUF → `.lbit.gguf`, numpy only, BF16 aware;
llama-family HF names only, others fail loudly), `produce_tiny.py` (**pipeline exercise only**, see below).

## M3 reference runtime and check

`lbref.py` is a numpy llama forward on `.lbit.gguf` or a dense GGUF. `check_ref.py` compares it to **upstream
PyTorch** (HF `LlamaForCausalLM` + upstream `LittleBitLinear`, weights loaded with upstream's own unpacking
loader). It runs on 4×64 tokens sampled from dense stories15M, on the box CPU.

Tiny models: stories15M (F32, 94 MiB), upstream init (Dual-SVID + `--use_itq`), then optionally 300 steps of
self-distillation QAT (KL to the dense model, AdamW lr 2e-3, bs 8×64, SmoothSign, 4 threads, ~6 min).
**Labeled `familia_provenance: pipeline-exercise`. This is not the paper recipe, and it is evaluated on text from
the same distribution it was distilled on, so quality numbers are optimistic.**

| model | linear bpw (stored, F32 scales) | max \|numpy − upstream\| logit | argmax agree | PPL (dense = 1.88) | top-1 = dense |
|---|---|---|---|---|---|
| init only, eff 1.0 | 1.106 | 2.9e-5 | 100% | 363 230 | 0% |
| init only, eff 0.55 | 0.644 | 1.8e-5 | 100% | 258 098 | 0% |
| init only, eff 0.1 (r=8) | 0.224 | 4.1e-5 | 100% | 2.7e14 | 0% |
| QAT 300, eff 1.0 | 1.106 | 2.7e-5 | 100% | **6.31** | 67.2% |
| QAT 300, eff 0.1 (r=8) | 0.224 | 3.5e-5 | 100% | **6.98** | 61.3% |

The runtime matches upstream to float32 rounding in every case. Init without QAT is useless (per-layer relative output
error is 0.82 SVD-only and 0.68 with ITQ at eff 1.0), so **QAT is not optional**. At 288-wide layers the F32 scales
dominate, which is why eff 0.1 stores 0.224 bpw. The 0.1 model's 42 linear layers take 167 KB (vs 22.8 MiB F32), and
greedy output is still story-like ("…She loved to play outside in the kitchen. One day, she found a big box…").
The file is still 71 MiB, because the F32 token_embd and output stay dense, as upstream does.

## M4 plug-and-play

```
# from an upstream LittleBit checkpoint (trained anywhere with SamsungLabs/LittleBit main.py)
scripts/scale_down.py --graph graph.yaml --node tiny --method littlebit \
    --from-checkpoint /path/to/ckpt --output ~/.local/share/gguf/models/tiny/tiny.lbit.gguf --runtime lbref
# planned (fails loudly today): --train-on hf-jobs   (needs a CUDA GPU job; HF credits, #36)
# pipeline exercise on CPU (graph form only): scale_down: {backend: littlebit, train_on: local-cpu-exercise,
#   upstream: /path/to/LittleBit, eff_bit: 0.1, qat_steps: 300, runtime: lbref, output: ...}
scripts/validate_graph.py --graph graph.scaled.yaml
```

The derived node gets `quant: littlebit` and the named runtime. The validator checks:

- a file marked `familia.quant=littlebit` needs `quant: littlebit` on its node, and the reverse;
- the runtime must list `quants: [littlebit]`, and a quant-only runtime refuses dense nodes;
- the format version must be 1;
- `--args` refuses `kind: reference` runtimes, because there is no HTTP server yet.

The manifest records the checkpoint sha256, the upstream config and the stored bpw.
`graph.yaml` declares the `lbref` runtime and has a commented example node. Tests: `python3 -m unittest
tests.test_littlebit` (8 tests, no torch or network; random factorized llama fixture with r=40 padding,
residual, q/k permute, scale_down + validator rules).

## What K2-Horizon-0.9B would look like (estimate, not run)

Linear layers 880.8 M params. With upstream's rank rule: eff 1.0 → 107 MiB, eff 0.55 → 60 MiB, **eff 0.1 → 11.6 MiB**
(ranks q/o 64, k/v 16, ffn 96). Embedding and the untied head are 64256×1536 each: 188 MiB f16, 53 MiB as Q4_0.
So on the 8600 GT the head, not the LittleBit layers, decides what fits. Blockers: a CUDA QAT run (≥1 epoch KD; not possible on our hosts),
plus `k2_horizon` arch support (yarn rope) in convert/lbref.

## Not done / next

1. A serving runtime: an HTTP shim around lbref for tests, then a C or ggml kernel. llama.cpp upstream has no LittleBit type.
2. A real QAT run (HF Jobs once credits exist) → `--train-on hf-jobs`.
3. More archs in convert/lbref (qwen2/3, k2_horizon).
4. The sm11 kernel ([littlebit-sm11-kernel.md](littlebit-sm11-kernel.md)), owned by the qodesh GPU work.
