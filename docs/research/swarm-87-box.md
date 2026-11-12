# P1: Google Harness? self-improving harness

Issue: https://github.com/brianreborn/familia/issues/87
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:30 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

**Integrate/test:** Integrate and test: (a) the proposed approach, (b) the files or
components likely involved, (c) risks and test ideas, (d) open questions. Do not
invent measurements, file contents or results; say 'unknown' instead.

**Source:** https://x.com/BrianReborn_alt/status/[number]

**Issue #87: P1: Google Harness? self-improving harness**

**Source:** https://x.com/BrianReborn_alt/status/[number]

**Integrate/test:** Integrate Google's open-source Harness? (self-improving
prompt/tools/memory/skills/subagents) as a first-class familia harness and as hermes's
self-improvement loop.

**Success criteria:**
- Harness? runs end-to-end under familia (launch, routing, logs).
- Benchmarked on the CentOS box and the phone vs hermes and plain llama.cpp on the same
  models, exact per-weight-file params recorded.
- Both hermes and Harness? covered by tests; results in docs/perf.

**Ref #86**

Write: (a) what the issue asks, in your own words, (b) a proposed approach and the
files or components likely involved, (c) risks and test ideas, (d) open questions. Do not
invent measurements, file contents or results; say 'unknown' instead.

**Source:** https://x.com/BrianReborn_alt/status/[number]

**Issue #87: P1: Google Harness? self-improving harness**

**Source:** https://x.com

-- swarm/box
