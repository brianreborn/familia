# Investigation: models for the CentOS Stream 10 big-RAM host

Status: **open, nothing measured on the host yet.** Tracking issue: [#70](https://github.com/brianreborn/familia/issues/70).
Written 2026-10-19 (PT). Every speed below is an **estimate** unless it has a link to a measurement.
Method follows the fleet rule: coarse binary search first (1 rep, short inputs), more resolution only
when candidates land within noise. Records must say `coarse binary search` in `note`.

## 1. Host facts

| fact | value | how it is known |
|---|---|---|
| OS | CentOS Stream 10, kernel 6.12, Weston (pixman) instead of GDM/Xorg | LESSONS-LEARNED.md `L-nvidia340` (commit 7ffdc63, written on the host) |
| GPU | GeForce 8600 GT (G84, CC 1.1, 256 MiB; `cuDeviceTotalMem` 255 MB) on the patched legacy 340.108 driver | same; CUDA driver test `cuInit(0)=0` passed |
| CPU ISA | **x86-64-v3 or better: AVX, AVX2, FMA, F16C, BMI1/2, LZCNT, MOVBE** | **inferred**: CentOS Stream 10 x86_64 targets v3 and does not run below it ([centos.org/centos10](https://centos.org/centos10/), [Red Hat](https://developers.redhat.com/articles/2024/01/02/exploring-x86-64-v3-red-hat-enterprise-linux-10)). So Haswell (2013) / Excavator (2015) or newer |
| CPU model, cores/threads, clocks, AVX-512 | **unknown** | not probed |
| RAM | "a lot" (owner); **size, DDR generation, channel count unknown** | not probed. Channel count matters more than size for speed |
| Disk | **unknown** | not probed. First wave needs ~75 GB free (see §4) |
| Host name / reachability | **unknown**. Not a registered familia machine; no SSH alias on miryam is confirmed to be it (the two existing aliases both timed out). Commits from it show `localhost.localdomain` | ListMachines, miryam `~/.ssh/config` Host lines |

Consequences:
- It is **not** the Athlon II X2 desktop (that CPU is x86-64-v1 and cannot boot EL10), even though it has the same GPU model. Whether the card was moved or is a second 8600 GT is an open question.
- AVX2/FMA/F16C are guaranteed, so stock llama.cpp CPU builds run at full speed; the no-AVX2 build question does not apply. `cmake -B build -DGGML_NATIVE=ON` (GCC 14 on EL10) or the official `ubuntu-x64` prebuilt (built with `GGML_CPU_ALL_VARIANTS`, glibc 2.39 on EL10 is new enough) both apply.
- The 8600 GT cannot run any LLM below; at most the gpu-legacy sm11 path (SmolLM2-135M, docs/perf/qodesh-gpu-legacy) as a decision side unit. On Linux the WDDM per-op sync cap seen on Windows should not exist: worth one experiment.
- Profile written: `registry/hardware/nvidia-g84-8600gt-x86v3-centos10.yaml` (unknowns are `null`); placeholder host key `centos10-bigram` in `registry/hosts.yaml`.

## 2. How the estimates were made

- **Token generation (tg)** is memory-bandwidth bound: `tg ≈ effective_BW / bytes_read_per_token`, with
  `bytes_read_per_token ≈ active_params × (file_size / total_params)`.
- **Effective bandwidth** = 37–59 % of theoretical. Calibrated on the only close public measurement found:
  [Netstero/on-prem-llm-cpu](https://github.com/Netstero/on-prem-llm-cpu), Xeon E5-2680 v4 (Broadwell, AVX2, no AVX-512), 64 GB quad-channel DDR4-2400 (76.8 GB/s theoretical), ik_llama.cpp, medians of 3:
  Qwen3-Coder-30B-A3B Q4 **22.5 t/s** at ~0.6k ctx and **9.1 t/s** at ~16k; gpt-oss-20b MXFP4 **13.6 t/s** / **10.9 t/s**.
  Qwen3-Coder implies ~59 % efficiency; gpt-oss sits just under the 37 % end. The range is the honest spread.
- Three bandwidth tiers because the RAM layout is unknown: dual-channel DDR3-1600 (25.6 GB/s, Haswell desktop), dual-channel DDR4-2400 (38.4), quad-channel DDR4-2400 (76.8, Xeon E5 v3/v4 workstation, the usual "lots of RAM" box).
- **Prompt processing (pp)** is compute bound: `pp ≈ 13 GFLOP/s per core·GHz × cores × GHz / (2 × active_params)`. The 13 comes from the same Netstero gpt-oss-20b run (16k cold prefill in ~308 s on 11 threads). Shown for 4C @ 3.5 GHz and 12C @ 2.6 GHz.
- **RAM @64K** = weights + f16 KV cache at 65,536 tokens (from each `config.json`: attention layers × KV heads × head dim × 2 × 2 bytes; sliding-window layers counted at their window) + 1 GiB for buffers. OS and other residents not included. `-ctk q8_0 -ctv q8_0` halves the KV part.
- Small-active models are where this model is weakest: on a 2-channel DDR4-3200 laptop (51.2 GB/s) LFM2.5-8B-A1B measured 16.5 t/s and Granite-4.0-H-Tiny 12.5 t/s, below what the formula gives (~21–33 and ~31–50). As bytes per token shrink, compute and per-token overhead take over, so treat the 1–1.5B-active rows as optimistic by up to ~2×.
- Hybrid models (Qwen3.5/3.6 Gated DeltaNet, LFM2 short-conv, Nemotron-H Mamba, Granite-H) have few attention layers, so KV is small and decode should slow less with depth than the dense-attention Qwen3-Coder-30B (22.5 → 9.1 t/s). That is a hypothesis to test, not a measurement.

## 3. Candidates (sizes and revisions from the HF API, 2026-10-19)

| model (GGUF repo) | total / active | quant, file | KV @16K / @64K (GiB) | RAM @64K (GiB, est.) | GB read / token | tg t/s est. @25.6 / 38.4 / 76.8 GB/s | pp t/s est. 4C / 12C | license |
|---|---|---|---|---|---|---|---|---|
| [unsloth/Qwen3.6-35B-A3B-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF) | 34.7B / 3B | UD-Q4_K_XL 22.36 GB (+mmproj F16 0.90) | 0.31 / 1.25 | 23.1 | 1.94 | 5–8 / 7–12 / 15–23 | 30 / 68 | Apache-2.0 |
| [unsloth/Qwen3-Coder-Next-GGUF](https://huggingface.co/unsloth/Qwen3-Coder-Next-GGUF) | 79.7B / 3B | UD-Q4_K_XL 49.61 GB | 0.38 / 1.50 | 48.7 | 1.87 | 5–8 / 8–12 / 15–24 | 30 / 68 | Apache-2.0 |
| [unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF](https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF) | 30.5B / 3.3B | UD-Q4_K_XL 17.67 GB | 1.50 / 6.00 | 23.5 | 1.91 | 5–8 / 7–12 / 15–24 (**measured 22.5** on quad DDR4-2400) | 28 / 61 | Apache-2.0 |
| [ggml-org/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF](https://huggingface.co/ggml-org/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF) | 31.6B / ~3.2B | Q4_0 18.90 GB | 0.09 / 0.38 | 19.0 | 1.92 | 5–8 / 7–12 / 15–24 | 28 / 63 | OpenMDW-1.1 |
| [LiquidAI/LFM2.5-24B-A2B-GGUF](https://huggingface.co/LiquidAI/LFM2.5-24B-A2B-GGUF) | 24.0B / 2.45B | Q4_K_M 14.53 GB | 0.31 / 1.25 | 15.8 | 1.49 | 6–10 / 10–15 / 19–31 | 37 / 83 | **LFM Open License v1.0** (custom, commercial limits) |
| [ggml-org/gemma-4-26B-A4B-it-GGUF](https://huggingface.co/ggml-org/gemma-4-26B-A4B-it-GGUF) | 25.2B / 3.8B | Q4_0 14.62 GB (+mmproj Q8_0 0.81) | 0.51 / 1.45 | 16.1 | 2.20 | 4–7 / 6–10 / 13–21 | 24 / 53 | Apache-2.0 |
| [ggml-org/gpt-oss-20b-GGUF](https://huggingface.co/ggml-org/gpt-oss-20b-GGUF) | 20.9B / 3.6B | MXFP4 12.11 GB | 0.38 / 1.50 | 13.8 | 2.08 | 5–7 / 7–11 / 14–22 (**measured 13.6**) | 25 / 56 | Apache-2.0 |
| [ggml-org/gpt-oss-120b-GGUF](https://huggingface.co/ggml-org/gpt-oss-120b-GGUF) | 116.8B / 5.1B | MXFP4 63.39 GB | 0.57 / 2.25 | 62.3 | 2.77 | 3–5 / 5–8 / 10–16 | 18 / 40 | Apache-2.0 |
| [unsloth/Qwen3.5-122B-A10B-GGUF](https://huggingface.co/unsloth/Qwen3.5-122B-A10B-GGUF) | 122.1B / 10B | UD-Q4_K_XL 77.03 GB | 0.38 / 1.50 | 74.2 | 6.31 | 2 / 2–4 / 5–7 | 9 / 20 | Apache-2.0 |
| [LiquidAI/LFM2.5-8B-A1B-GGUF](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B-GGUF) | 8.5B / 1.5B | Q4_K_M 5.16 GB | 0.19 / 0.75 | 6.6 | 0.91 | 10–17 / 16–25 / 31–50 (measured [16.5](https://www.utkarshruhela.com/benchmarking-local-inference) on Ryzen 3 5300U 2ch DDR4-3200, [20.99](https://huggingface.co/ljupco/cpu-only-inference-models/blob/main/docs/lfm2-maple-4bit-report.md) Q4_0h on i5-8350U) | 61 / 135 | LFM Open License v1.0 |
| [ibm-granite/granite-4.0-h-tiny-GGUF](https://huggingface.co/ibm-granite/granite-4.0-h-tiny-GGUF) | 6.9B / ~1B | Q4_K_M 4.23 GB | 0.12 / 0.50 | 5.4 | 0.61 | 16–25 / 23–37 / 47–74 (measured [12.5](https://www.utkarshruhela.com/benchmarking-local-inference) on the 5300U: our model is optimistic here) | 91 / 203 | Apache-2.0 |
| [inclusionAI/Ling-3.0-tiny-GGUF](https://huggingface.co/inclusionAI/Ling-3.0-tiny-GGUF) | 7.9B / 1.3B | Q4_K_M 4.82 GB | **3.00 / 12.0** | 17.5 | 0.79 | 12–19 / 18–29 / 36–57 | 70 / 156 | MIT |
| Qwen3.5-9B (dense, reference) | 9.0B / 9.0B | Q4_K_M 5.68 GB | 0.50 / 2.00 | 8.3 | 5.68 | 2–3 / 3–4 / 5–8 | 10 / 23 | Apache-2.0 |
| Qwen3.6-27B (dense, reference) | 26.9B / 26.9B | Q4_K_M 16.82 GB | 1.00 / 4.00 | 20.7 | 16.82 | ~1 / ~1 / 2–3 | 3 / 8 | Apache-2.0 |
| [tencent/HY-MT1.5-7B-GGUF](https://huggingface.co/tencent/HY-MT1.5-7B-GGUF) (translation) | 7.5B dense | Q6_K 6.16 GB | 2.0 @16K (4K is plenty) | ~7.7 @4K | 6.16 | 2 / 2–4 / 5–7 | 12 / 27 | not in HF metadata; the 1.8B sibling is Tencent HY Community (not valid in EU/UK/KR) — **verify** |
| [Qwen/Qwen3-Embedding-4B-GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-4B-GGUF) | 4.0B dense | Q8_0 4.28 GB | n/a | ~5 | — | — (embedding = prefill only) | 23 / 50 tokens/s embedded | Apache-2.0 |
| [Qwen/Qwen3-Embedding-8B-GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-8B-GGUF) | 7.6B dense | Q8_0 8.05 GB | n/a | ~9 | — | — | 12 / 27 | Apache-2.0 |
| unsloth/embeddinggemma-2-GGUF (in registry) | 0.27B | Q8_0 0.31 GB | n/a | <1 | — | — | very fast | Apache-2.0 |
| [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp) large-v3-turbo | 0.8B | q5_0 0.57 GB | — | ~1.5 | — | — | — | MIT |
| [audio-cpp/Nemotron-3-Diarization-GGUF](https://huggingface.co/audio-cpp/Nemotron-3-Diarization-GGUF) (#55) | 99M | q8_0 0.11 GB | — | <1 | — | — | — | OpenMDW-1.1 |

Dense models are listed only to show why they lose here: a 9B dense model reads ~3× more bytes per token than a 35B-A3B MoE.

### Required launch parameters (from the cards; snapshots pinned under `hf-meta/` on miryam)

| model | REQUIRED | sampling the card recommends |
|---|---|---|
| Qwen3.6-35B-A3B | `--jinja`; thinking on by default (turn off with `--chat-template-kwargs '{"enable_thinking":false}'`); card: "maintain a context length of at least 128K tokens to preserve thinking capabilities" → at 64K run non-thinking or accept the risk | thinking/general `temp 1.0 top_p 0.95 top_k 20 min_p 0 presence 1.5`; thinking/coding `temp 0.6 … presence 0`; non-thinking `temp 0.7 top_p 0.8 top_k 20 presence 1.5` |
| Qwen3-Coder-Next | `--jinja`; non-thinking only | `temp 1.0 top_p 0.95 top_k 40` (unsloth adds `min_p 0.01`) |
| Qwen3-Coder-30B-A3B | `--jinja`; non-thinking only | `temp 0.7 top_p 0.8 top_k 20 repeat 1.05` |
| Nemotron-3.5-Lightning | `--jinja`; reasoning on by default (`enable_thinking`) | `temp 1.0 top_p 0.95`; card's own llama.cpp line `-c 40960 -fa on --jinja` |
| LFM2.5-24B-A2B | always thinks (`<think>` added by the template); Pythonic tool calls between `<\|tool_call_start\|>`/`<\|tool_call_end\|>` | `temp 0.1 top_k 50 repeat 1.05` (also in GGUF `general.sampling.*`) |
| gemma-4-26B-A4B-it | thinking only if `<\|think\|>` starts the system prompt; strip prior thoughts from history | `temp 1.0 top_p 0.95 top_k 64` |
| gpt-oss-20b / 120b | **harmony format** (`--jinja`, the GGUF's template); YaRN ×32 is in the GGUF; reasoning effort low/medium/high in the system prompt | card has no fixed sampler |
| HY-MT1.5-7B | no system prompt; use the card's prompt templates | `temp 0.7 top_k 20 top_p 0.6 repeat 1.05` |
| Qwen3-Embedding | `--embedding --pooling last`; queries need the `Instruct: …\nQuery:` prefix | — |

llama.cpp support: all arches above (`qwen35moe`, `qwen3next`, `qwen3moe`, `nemotron_h_moe`, `lfm2moe`, `gemma4`, `gpt-oss`, `granitehybrid`, `bailingmoe3`, `hunyuan-dense`, `qwen3`) are published as GGUF by ggml-org, unsloth or the vendor for llama.cpp. Not yet checked against **our pinned build**: LFM2.5-24B-A2B (released 2026-10-13), Nemotron 3.5, Ling-3.0. Qwen3-Next CPU decode was ~5× too slow until native Gated-DeltaNet kernels landed ([llama.cpp #19480](https://github.com/ggml-org/llama.cpp/issues/19480), fixed by PR #20334): use a build after that. For hybrid models prompt-cache reuse needs context checkpoints (`--ctx-checkpoints`, `--cache-ram`; fixes in PRs #20428, #23121).

## 4. Shortlist by role

RAM size decides which column applies; channel count decides speed.

| role | 1st | 2nd | 3rd | 4th |
|---|---|---|---|---|
| **coder** (hermes, ≥64K ctx) | Qwen3.6-35B-A3B UD-Q4_K_XL — best coding score of the 3B-active group in the table Liquid published (SWE-Bench Verified 66.2, vendor-reported), small KV, vision via mmproj | Qwen3-Coder-Next UD-Q4_K_XL — **only with ≥64 GB**; non-thinking, so no reasoning tokens to pay for on CPU | Qwen3-Coder-30B-A3B UD-Q4_K_XL — the one with a real CPU measurement on comparable hardware; big KV (use q8_0 KV) and decode drops with depth | Nemotron-3.5-Lightning Q4_0 — tiniest KV (0.38 GiB at 64K), 1M ctx |
| **general / agent** (hermes graph) | LFM2.5-24B-A2B Q4_K_M — fewest bytes per token of the big models, trained inside Hermes Agent, 131K ctx; but always thinks and has a custom license | Qwen3.6-35B-A3B (share one server with coder) | gemma-4-26B-A4B-it Q4_0 (vision, Apache-2.0) | gpt-oss-20b MXFP4 (measured on similar hardware); gpt-oss-120b only with ≥96 GB |
| **fast general / decision** | LFM2.5-8B-A1B Q4_K_M (measured 16.5–21 t/s on 2-channel laptops) | granite-4.0-h-tiny Q4_K_M | keep the registry deciders (SmolLM2-135M, Julia-1, Laya) on CPU; SmolLM2 on the 8600 GT via gpu-legacy as an experiment | d3-nano (#53, Qwen3.5-2B base, Apache-2.0) needs a GGUF conversion first. GEV-26B-Decide stays blocked (its GGUF has no adapter/head, see registry/model-params.yaml) |
| **embed** | embeddinggemma-2 Q8_0 (registry) for bulk indexing: prefill-bound, so small wins on CPU | Qwen3-Embedding-4B Q8_0 for quality on small corpora | Qwen3-Embedding-8B Q8_0 | — |
| **language** | HY-MT1.5-1.8B (registry) for speed | HY-MT1.5-7B Q6_K for quality (dense, 2–7 t/s est.; license to verify) | Qwen3.6-35B-A3B (201 languages, faster per token than the 7B dense) | — |
| speech / vision | whisper.cpp large-v3-turbo q5_0; Nemotron-3-Diarization q8_0 (needs audio-cpp, not llama.cpp) | vision: Qwen3.6 mmproj or gemma-4 mmproj | — | — |

Survey items checked and not shortlisted: Ternary Bonsai 2 (#54; PTQ1_0 needs PrismML's kernels, verify upstream support before testing), Qwen3.5-9B Kimi-K3 distill (#57; dense, q8_0 only), Ling-3.1 Flash and MiMo-V2.6-Pro (#57; ~300 GB+), PersonaPlex-7B (#55; GPU), Qwen-Image-2.1 (#56; CPU possible but slow), AgentHorse-4B (registry; license unknown).

Fit by RAM size (weights + 64K KV, before OS and other residents):
- **32 GB:** Qwen3.6-35B-A3B alone (~23 GiB) or LFM2.5-24B-A2B (~16) + small helpers.
- **64 GB:** Qwen3-Coder-Next alone (~49), or Qwen3.6-35B-A3B + LFM2.5-24B-A2B together (~39) + embed/decision.
- **≥96–128 GB:** gpt-oss-120b (~62) or Qwen3.5-122B-A10B (~74, 2–7 t/s est.) on top of the 64 GB set.
Residents share one memory bus: two decoding at once each run slower (miryam saw this, docs/ram-safety.md). Measure concurrency before making several resident.

**The real wall is prefill, not decode.** At an estimated 30–70 t/s pp, a cold 16K prompt takes ~4–9 min and a cold 64K prompt ~15–35 min (Netstero measured ~5–12 min at 16K on 11 Broadwell threads). Hermes is usable only if its long, stable prefix is cached: keep the system prompt byte-stable and test `--cache-reuse` / `--ctx-checkpoints` / `--cache-ram` / slot save-restore.

## 5. Test plan

**Phase 0 — host facts (read-only, nothing installed or changed):**
`lscpu; nproc; free -h; head -20 /proc/meminfo; /lib64/ld-linux-x86-64.so.2 --help | grep x86-64-v; sudo dmidecode -t memory | grep -E 'Size|Speed|Type:|Locator'` (dmidecode only if the owner OKs sudo; it reveals channel population); `lspci | grep -i -E 'vga|3d|nvidia'; df -h; uname -a`. Fill the `null`s in the hardware profile and add a `hosts:` entry to graph.yaml (no address in the public file).

**Phase 1 — runtime:** build the fleet's pinned llama.cpp CPU-only (`-DGGML_NATIVE=ON`) and record the `system_info` line (AVX2/FMA/F16C/AVX512). Also try the official ubuntu-x64 prebuilt for comparison. ik_llama.cpp is optional (it beat mainline at depth in the Netstero study).

**Phase 2 — anchors (small, already on disk elsewhere):** SmolLM2-135M Q4_0 and LFM2.5-1.2B Q4_K_M, `llama-bench -p 64 -n 32 -r 1`, threads ∈ {1, cores/2, cores}. Compares the host with miryam and gives the effective bandwidth (tg × bytes/token) that replaces the estimate tiers above.

**Phase 3 — coarse binary search (1 rep, `-p 512 -n 64 -r 1`), one model resident at a time, smallest download first:**
LFM2.5-8B-A1B → LFM2.5-24B-A2B → gpt-oss-20b → Qwen3.6-35B-A3B → Nemotron-3.5-Lightning (≈75 GB of downloads), then Qwen3-Coder-Next / gpt-oss-120b only if RAM ≥ 64 / 96 GB.
- threads: start at physical cores, halve once; keep the better one.
- depth: one run at `-d 16384` and one at `-d 65536` (f16 KV), then q8_0 KV only if f16 does not fit.
- quant: only if two models land within noise (±10 %), try the next quant up/down for those two.
- proposed pass bar for an interactive coder/general node: tg ≥ 8 t/s at 16K depth and pp ≥ 30 t/s (**owner to confirm**).

**Phase 4 — end-to-end:** hermes `--model` against the winner at 64K: cold and warm time to first token with prefix caching on, plus one concurrency run (coder + embed).

Record every run in `registry/records.jsonl` with `host: centos10-bigram` (rename later), `hardware_profile: nvidia-g84-8600gt-x86v3-centos10`, `note: "coarse binary search (1 rep, short pp/tg; reduced precision)"`.

Metadata only so far: card/config/tokenizer/license snapshots of the shortlist were fetched with `scripts/hf_fetch.py` (skips files > 50 MB, pinned to the revisions in the table) into `hf-meta/` on miryam. **No weights downloaded.** Before any weight download, `scripts/licenses.py review` must be run by the owner: LFM Open License v1.0, OpenMDW-1.1 and the Tencent HY license are custom terms.

## 6. Open questions

1. CPU model, cores/threads, AVX-512? RAM size, DDR3 or DDR4, how many channels populated? Free disk?
2. Host name, and how familia should reach it (SSH alias, registered machine)?
3. Same 8600 GT as the Windows desktop (moved), or a second card?
4. Pass bars for "works": tg and time-to-first-token targets per role.
5. Which custom licenses are acceptable (LFM, OpenMDW, Tencent HY)?
6. Should this host take the graph's coder/general roles from miryam (whose 7 GiB caps it at 2B-class), with miryam/phones keeping decision and embed?
