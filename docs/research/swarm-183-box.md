# TOP PRIORITY: performance-test all models against real benchmarks (speed + quality, per host:user)

Issue: https://github.com/brianreborn/familia/issues/183
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:39 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

**Issue #183: TOP PRIORITY: performance-test all models against real benchmarks (speed + quality, per host:user)**

**TOP PRIORITY (Brian, [number]):** performance-test every model we ship or route to against real, published benchmarks, as soon as possible.

**Scope:** every model in `models-preset.ini` and the familia catalogs, including the router, the roles, embed, the proto-chat bootstrap models, and the specialty candidates (Galactica 125M, ArXiv-to-Model).

**Measure**
1. **Speed:** prompt-processing and generation tok/s, time to first token, and peak RAM/VRAM, using `llama-bench` plus real server requests. Report each per host:user and per quant.
2. **Quality:** use real public benchmarks matched to each model's role, run through lm-evaluation-harness or the equivalent against the llama-server OpenAI endpoint.
   - general: MMLU-Pro subset, ARC, HellaSwag
   - reasoning: GSM8K, with reasoning on and off
   - code: HumanEval/MBPP
   - tool use and routing: BFCL subset
   - embedding: MTEB subset
3. **Regression gate:** store the baselines, and flag any significant drop on a new pin or model.

**Rules**
- The swarm runs it on its runners. CPU is fine; use smaller benchmark subsets first.
- Downloads are pre-approved up to about 10 GB per host. Nothing uses sudo.
- Results are posted here as tables. Raw logs go to familia-private only. No

-- swarm/box
