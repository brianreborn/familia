# Models catalog

Every model familia runs, plans to run, or has been pointed at (the user's RTs,
classified in [#20](https://github.com/brianreborn/familia/issues/20)). Nothing
here is auto-picked. A model runs only when a `models:` entry and a `nodes:`
entry in `graph.yaml` say so. Unplaced entries live under `options:` (catalog
only: never placed or counted against RAM).

Sizes come from the Hugging Face API (checked 2026-10-09 PT) or the RT text,
and the source is marked on each one. "unknown" means nobody has verified it. Do not guess.

## RAM budgets (docs/ram-safety.md)

A model fits only if weights + KV + 256 MiB overhead stay under **both** limits:
the host's `ram_mib - reserve_ram_mib` and 60% of `ram_mib`.

| Host | ram_mib | reserve | Budget for models | Already used |
|---|---|---|---|---|
| miryam | 7270 | 3072 | ~4198 MiB | coder + embed est. 3479 MiB, leaving ~700 MiB |
| qodesh | 16379 | 4096 | ~9827 MiB (60% cap) | CPU coder + GPU decision (8600 GT, 256 MB VRAM) |
| a57 phones (phone7/phone8, feat/android-hosts) | ~7.4 GB measured | not set | ~4.4 GB (60%) | none |
| note9, pixel8, shalom, godslove | unmeasured | | unknown | |

Status values: **in graph** = a `models:` entry exists. **planned** = a
linked issue is working on it. **candidate** = an `options:` entry only.

## Text / coder / decision / embed

| Graph key | Role | Arch | Size and quant | Runtime | Fits | Status | Source |
|---|---|---|---|---|---|---|---|
| qwen35-2b-q4km | coder | qwen35 | Qwen3.5-2B Q4_K_M (est. ~2.9 GiB at 64k ctx) | llama-server pinned build | miryam | in graph | — |
| egemma2-q8 | embed | gemma-embedding2 | EmbeddingGemma 2 Q8_0 | llama-server | miryam (tight) | in graph | [RT](https://x.com/BrianReborn_alt/status/2107564534047395851) |
| stories15m-fp32 | decision | llama2c | 15M fp32 | qodesh legacy-GPU runtime | qodesh 8600 GT | in graph (feat/qodesh-gpu-decision) | — |
| smollm2-135m-q4 | decision | llama | SmolLM2-135M-Instruct Q4_0, 87 MiB | qodesh legacy-GPU runtime | qodesh 8600 GT | in graph (feat/qodesh-gpu-decision) | — |
| qwen35-9b-coder | coder | qwen35 (claimed) | 9B; Q4_K_M ~5.5 GB (estimate) | llama-server | qodesh only | planned #26 | [RT](https://x.com/BrianReborn_alt/status/2108600815808336061) |
| drex-1.5 | decision | Qwen3_5ForCausalLM | 8.95B; [Q8_0](https://huggingface.co/nace-ai/drex-v1.5-Q8_0) 9.53 GB; [Q4_K_M](https://huggingface.co/mradermacher/drex-v1.5-GGUF) 5.63 GB; Q2_K 3.83 GB; extra `head.pt` | llama-server (qwen35) + decision head support unverified | qodesh CPU (Q4); **not** the 256 MB GPU | planned #24 | [RT](https://x.com/BrianReborn_alt/status/2108691502864163123) · [HF](https://huggingface.co/nace-ai/drex-v1.5) |
| drex-1.1 | decision | diffusion LM | unknown (maybe [nace-ai/drex-dlm](https://huggingface.co/nace-ai/drex-dlm), 8.19B, cc-by-nc-4.0, not confirmed) | drex-dlm / `llama-server__nace-ai__edlm` pin | qodesh CPU if 8B | candidate | [RT](https://x.com/BrianReborn_alt/status/2107800181316141401) |
| k2-type-0.9b | decision | unknown | 0.9B; ~0.5 GB Q4 (estimate) | unknown | qodesh GPU (heavy quant), miryam | planned #24 | [RT](https://x.com/BrianReborn_alt/status/2106354389611094041) |
| glide | decision | unknown | unknown | unknown | unknown | candidate | [RT](https://x.com/BrianReborn_alt/status/2107815038589567062) |
| cloudflare-clef | decision | unknown | unknown | unknown | unknown | candidate | [RT](https://x.com/BrianReborn_alt/status/2106238504938377271) |
| gev-26b-decide | decision | unknown | 26B; ~15 GB Q4 (estimate) | unknown | none | candidate (catalog only) | [RT](https://x.com/BrianReborn_alt/status/2107731560246215067) |
| decision-2.0 | decision | unknown | 0.6B–27B family | unknown | 0.6B maybe qodesh GPU | candidate | [RT](https://x.com/BrianReborn_alt/status/2106237127449362760) |
| kev-1.0 | decision | unknown | unknown | unknown | unknown | candidate | [RT](https://x.com/BrianReborn_alt/status/2106235881904599179) |
| jev-cpu-decision | decision | unknown | unknown | CPU (per post) | unknown | candidate | [RT](https://x.com/BrianReborn_alt/status/2106949194913366275) |
| jp-decision-gguf | decision | unknown | unknown (GGUF) | llama-server | unknown | candidate | [RT](https://x.com/BrianReborn_alt/status/2106236190940950767) |
| qwen35-0.8b-jp | chat | qwen35 | 0.8B (file unknown) | llama-server pinned build | miryam/phones likely | candidate | [RT](https://x.com/BrianReborn_alt/status/2106236078533550141) |
| tencent-translate-440mb | chat (MT) | unknown | ~440 MB (post) | unknown | phones likely | candidate | [RT](https://x.com/BrianReborn_alt/status/2105728713950437842) |
| index-translate | chat (MT) | Qwen3.5-based (post) | unknown | unknown | unknown | candidate | [RT](https://x.com/BrianReborn_alt/status/2105389175872847935) |
| dolphin3-cyber-8b | pentest | unknown | ~3.2 GB Q2_K (post) | llama-server | qodesh | candidate (docs/pentest-models.md) | RT 2026-09-20 |

## Vision / parsing / speech

| Graph key | Role | Arch | Size | Runtime | Fits | Status | Source |
|---|---|---|---|---|---|---|---|
| youtu-parsing-omni | vision/parsing | youtu_vita (custom) | ~5B, bf16 ~10.7 GB | transformers / vLLM + plugin; no llama.cpp | none at bf16 | candidate | [RT](https://x.com/BrianReborn_alt/status/2108756031493025930) · [HF](https://huggingface.co/tencent/Youtu-Parsing-Omni) |
| lift-extract | vision/parsing | unknown | unknown | unknown | unknown | candidate | [RT](https://x.com/BrianReborn_alt/status/2106703750262141361) |
| whistle-stt | stt | Cactus | `whistle.cact` 16.9 MB; safetensors 220.6 MB; apache-2.0 | Cactus runtime | phones, qodesh | planned #25 | [RT](https://x.com/BrianReborn_alt/status/2108691766589415772) · [HF](https://huggingface.co/Cactus-Compute/whistle) |
| paradee-tts | tts | Kokoro distill | 8M; ONNX int8 9.0 MB / fp 37.0 MB; apache-2.0 | ONNX Runtime | phones, qodesh | planned #25 | [RT](https://x.com/BrianReborn_alt/status/2108070180769407307) · [HF (likely)](https://huggingface.co/sahilmahendrakar/Paradee-8M-v1.0) |
| voice-clone-1.7b | tts | unknown | 1.7B (post) | unknown | unknown | candidate | [RT](https://x.com/BrianReborn_alt/status/2108533834400850249) |

## Remote only (not graph models)

- **Qwen3.8-27B through `ssh chat.hf.co`** ([RT](https://x.com/BrianReborn_alt/status/2108600920850444631)): this is an
  `isolated_remote` node (feat/isolated-compute), not a local model. It is blocked
  on HF credits (#36), since all 128 models in the picker return 402.

## RT'd but not models (tracked elsewhere)

Heretic uncensoring tool (code-bootstraps-llama.cpp, policy-sensitive), Uzu
runtime (code-bootstraps-llama.cpp#21), Living Weights / Hindsight
(green-agentz#16), Unsloth decision-model training (code-bootstraps-llama.cpp#20),
Samsung LittleBit (feat/scale-down), OmniRoute/OrcaRouter (green-roomz#27),
LeWAM 17M JEPA world-action model (robotics planning, RT 2026-10-09; not an LLM role).
