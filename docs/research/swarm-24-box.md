# Decision-model catalog for the always-on GPU role (Drex 1.5/1.1, GLiDE, K2-Type-0.9B, Clef, GEV-26B-Decide)

Issue: https://github.com/brianreborn/familia/issues/24
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:42 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

## Tasks
- [x] Resolve the HF repo, license and GGUF for each model
- [ ] Add catalog entries with RAM/VRAM estimates (validator, RAM safety reserve)
- [ ] Measure the smallest one on the 8600 GT path and on CPU

Related: code-bootstraps-llama.cpp#9 (decision model stays available).

Write: (a) what the issue asks, in your own words, (b) a proposed approach and
the files or components likely involved, (c) risks and test ideas, (d) open
questions. Do not invent measurements, file contents or results; say
'unknown' instead.
```

## Tasks
- [x] Resolve the HF repo, license and GGUF for each model
- [ ] Add catalog entries with RAM/VRAM estimates (validator, RAM safety reserve)
- [ ] Measure the smallest one on the 8600 GT path and on CPU

Related: code-bootstraps-llama.cpp#9 (decision model stays available).

Write: (a) what the issue asks, in your own words, (b) a proposed approach and
the files or components likely involved, (c) risks and test ideas, (d) open
questions. Do not invent measurements, file contents or results; say
'unknown' instead.
```

## Tasks
- [x] Resolve the HF repo, license and GGUF for each model
- [ ] Add catalog entries with RAM/VRAM estimates (validator, RAM safety reserve)
- [ ] Measure the smallest one on the 8600 GT path and on CPU

Related

-- swarm/box
