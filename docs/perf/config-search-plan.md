# Config search plan: desktop, miryam laptop, Android phone

Status: plan, 2026-10-19 (PT). Machine-readable space: [config-search-space.yaml](config-search-space.yaml).
Speculative decoding: [#91](https://github.com/brianreborn/familia/issues/91) (draft) vs #82 (n-gram).

> **Old results gathered under per-launch memcg caps are invalid** (LESSONS-LEARNED `L-memcg`, #95):
> `2026-10-19-tuning-2.md`, `2026-10-19-hermes-prompt.md` and anything else run with `systemd-run -p MemoryMax`
> or "peak + 15 %" caps with swap 0. Rerun them via `scripts/rerun_all.sh`; never set such caps in this search.

## Rules for every result
- **Launch status protocol:** every launch goes through `scripts/launch_matrix.py` (which runs
  `bench_guard.py check / meta / flags`) and is classified as exactly one of
  `OK, BAD_PARAMS, OOM, MISSING_RUNTIME, ENGINE_BUG, MODEL_FILE, TIMEOUT`, with a `why`. A death that has no class
  doesn't go in the results. Read the kill line (memcg vs global OOM vs oomd) before calling something OOM.
- Label models by **name + version + quant** (e.g. `Qwen3.5-2B Q4_K_M`), never by file hash.
- Record the **exact params per weight file** (full argv after `bench_guard flags`, plus documented defaults).
- `note` contains `coarse binary search` for sweep points; RAM: MemAvailable must stay >= host reserve.
- Never skip a model for license reasons.
- No addresses, logins, ports or keys in results; hosts by graph.yaml key.

## Hosts (from graph.yaml)
| host key | role | CPU / threads | RAM / reserve | GPU |
|---|---|---|---|---|
| centos10-bigram (desktop) | big models, coder+general candidate | i5-4570, 4C/4T AVX2 | 23 GiB / 6 GiB | 8600 GT 256 MiB, legacy 340 driver, gpu-legacy sm11 path only |
| miryam (laptop) | hermes host, coder today | i5-7200U, 4 threads | 7.1 GiB / 3 GiB | HD 620 Vulkan (slower than CPU) |
| phone8 (Android; phone7 twin) | decision / small general | 3 usable threads (A520/A720) | 7.3 GiB / 5 GiB | Xclipse 550 Vulkan, verified |

Open question: graph.yaml marks the desktop GPU `unsupported` (nouveau bound), while
centos-bigram-models.md reports the 340.108 driver passing `cuInit`. Probe this before running any GPU sweep.

## Dimensions
model x quant x threads x batch/ubatch x ctx x load mode (mmap / none / mlock) x flash-attn (+ KV type) x
speculative (none / ngram-simple / draft-simple pairs) x GPU offload x concurrency set x harness
(plain llama-server, hermes single, hermes --graph, Harness²). Values per host are in the YAML.

## Method
1. **Prune with the placement predictor:** `scripts/plan_placement.py registry/links/<host>.jsonl FILE.gguf
   --active-frac F` predicts tg for CPU vs the VRAM prototype. Drop points predicted < 0.5x of the host's best
   or over the RAM budget. GPU offload is only tried where the predictor says the weights fit in free VRAM.
   Record the predicted vs measured error (target within 30 %).
2. **Coarse binary search per dimension** (1 rep, short prompt): for ordered dims (threads, ubatch, ctx, draft n_max)
   test the ends and the midpoint, then keep halving toward the better side. For binary dims (fa, load mode)
   test both. Hold the others at the current best.
3. **Cross the frontier:** combine the top-2 per dimension; refine with 3 reps only where candidates are within 10 %.
4. **Quality** on the top-k per host with the small suite from the routing plan: smoke-5, GSM8K-100,
   HumanEval+-50, BFCL-simple-50, MT-Bench-10. The judge is the strongest local node, labelled as such.
   Speculative configs must match the non-spec output at temp 0 (no quality loss, per #91).
5. **Concurrency** sets on the top-3 per host (tg/TTFT inflation, combined RSS, MemAvailable floor).
6. **Harness** pass on the winner: plain llama-server, `hermes.sh --mode single`, `hermes.sh --mode graph`, Harness² (eval only).

## Objectives
tg tok/s, TTFT, peak RSS (all maximized or minimized jointly; Pareto front reported), and quality pass-rate.

## Top 10 configs to try first
1. desktop: Qwen3.5-2B Q4_K_M, -t 2 -lm none -fa 1 -ctk/v q8_0, ctx 65536, spec draft-simple with Qwen3-0.6B Q8_0, n_max 8
2. desktop: Qwen3.5-2B Q4_K_M, same, spec ngram-simple (baseline against #91)
3. desktop: LFM2.5-8B-A1B Q4_K_M, -t 4 -lm none -fa 1, ctx 32768, ub 512
4. desktop: Qwen3.5-9B Q4_K_M, -t 4 -lm none -fa 1, ctx 32768, draft Qwen3-0.6B Q8_0 n_max 8
5. desktop: gpt-oss-20b MXFP4, -t 4 -lm none -ub 512, ctx 32768
6. desktop: concurrency set coder (Qwen3.5-2B, -t 2) + general (LFM2.5-1.2B, -t 1) + Laya (-t 1), plain + hermes --graph
7. miryam: Qwen3.5-2B Q4_K_M -t 3 -lm none --slot-save, ctx 65536, ngram-simple vs draft LFM2.5-350M / Qwen3-0.6B, via hermes single
8. miryam: SmolLM2-135M Q4_0 Vulkan -ngl 99 decision + coder concurrently (RAM floor check)
9. phone8: LFM2.5-1.2B Q4_K_M Vulkan -ngl 99 -fa 1 -t 3, ctx 4096, draft LFM2.5-350M n_max 4
10. phone8: Qwen2.5-0.5B Q4_K_M Vulkan -ngl 99 -fa 1 -t 3 vs CPU -t 3, ctx 4096 (placement predictor check)
