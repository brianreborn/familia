# P1: Tencent Terminal-RSI recursive self-improvement

Issue: https://github.com/brianreborn/familia/issues/88
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:32 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

**Integrate/test:** Implement the Terminal-RSI recipe (self-rewrite of successful trajectories + policy refinement) as a familia agent-tuning pipeline.

**Success criteria:**
- Pipeline collects trajectories and produces refined prompts/policies in familia.
- Measurable terminal-task success gain on a fixed suite, benchmarked on the CentOS box and the phone (where model fits), exact per-weight-file params recorded.
- Works with both hermes and Harness?.

Ref #85

Write: (a) what the issue asks, in your own words, (b) a proposed approach and
the files or components likely involved, (c) risks and test ideas, (d) open
questions. Do not invent measurements, file contents or results; say
'unknown' instead.
**Integrate/test:** Implement the Terminal-RSI recipe (self-rewrite of successful trajectories + policy refinement) as a familia agent-tuning pipeline.

**Success criteria:**
- Pipeline collects trajectories and produces refined prompts/policies in familia.
- Measurable terminal-task success gain on a fixed suite, benchmarked on the CentOS box and the phone (where model fits), exact per-weight-file params recorded.
- Works with both hermes and Harness?.

Ref #84

Write: (a) what the issue asks, in your own words, (b) a proposed approach and
the files or components likely involved, (c) risks and test ideas, (d) open
questions. Do not invent measurements, file contents or results; say
'unknown' instead.
**Integrate/test:** Implement the Terminal-RSI recipe (self-rewrite of successful trajectories + policy ref

-- swarm/box
