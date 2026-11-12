# P1: PrismML Bonsai 2 ternary models (2B/4B/9B)

Issue: https://github.com/brianreborn/familia/issues/93
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:34 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

**Bonsai 2 (2B/4B/9B ternary, Qwen3.5-based, tool calling) is a new model in the
registry for CPU, phone and old hardware. It is a ternary model (2B/4B/9B) with
ternary tool calling. It is a new model in the registry for CPU, phone and old hardware.

**Integrate/test:** Add PrismML Bonsai 2 to the model registry for CPU, phone and old hardware.

**Success criteria:**
- Models load and serve in familia with validated GGUF metadata (or documented defaults).
- Benchmarked on the CentOS box and the phone, exact per-weight-file params recorded.
- Tool calling tested via both hermes and Harness?.

Ref #86

Write: (a) what the issue asks, in your own words, (b) a proposed approach and the
files or components likely involved, (c) risks and test ideas, (d) open questions. Do not
invent measurements, file contents or results; say 'unknown' instead.

**Source:** https://x.com/BrianReborn_alt/status/[number]

**Integrate/test:** Add PrismML Bonsai 2 (2B/4B/9B ternary, Qwen3.5-based, tool calling) to the model registry for CPU, phone and old hardware.

**Success criteria:**
- Models load and serve in familia with validated GGUF metadata (or documented defaults).
- Benchmarked on the CentOS box and the phone, exact per-weight-file params recorded.
- Tool calling tested via both hermes and Harness?.

Ref

-- swarm/box
