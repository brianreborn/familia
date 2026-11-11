# Research: Single-neuron steering (composable persona/behavior neurons)

Issue: https://github.com/brianreborn/familia/issues/206
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:43 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

**Write:** This issue asks for research on single-neuron steering. Several reports show behavior can be steered by dosing a handful of MLP neurons: a 'catgirl' persona composed from a partial neuron atlas in Qwen, 6 'yandere' neurons in LFM3-1.7B GGUF, and 'evil qwen' from two neurons in Qwen3.5-4B. Possible relevance to familia: a cheap runtime control-vector/neuron-dose mechanism in llama.cpp could give per-agent personas or unlocked variants without separate fine-tuned weights. Not part of the v0.2 or v0.3 sprint.

**Write:** (a) what the issue asks, in your own words, (b) a proposed approach and the files or components likely involved, (c) risks and test ideas, (d) open questions. Do not invent measurements, file contents or results; say 'unknown' instead.

-- swarm/box
