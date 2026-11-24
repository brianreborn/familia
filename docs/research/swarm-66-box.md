# RRSI: regularized recursive self-improvement for Harness? optimizer

Issue: https://github.com/brianreborn/familia/issues/66
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:19 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

- **What to do next:** (a) find the right paper, (b) find the right code, (c) find the right API calls, (d) find the right local-2B scale, (e) find the right model, (f) find the right policy and proposer, (g) find the right jobBench metrics, (h) find the right survey line. See also #59.

## RRSI: regularized recursive self-improvement for Harness?

**Status: research / design only. Not implemented.** Moved out of #59. A possible improvement to the Harness? loop in #65. See also Terminal-RSI (#68).

## Source (quoted from #59)

- **[RRSI ? Regularized Recursive Self-Improvement of Agent Harnesses](https://arxiv.org/abs/2609.24972)** ? Regularizes automated agent-harness evolution to prevent overfitting. Up to 4.3 points on the five out-of-distribution benchmarks, and a harness that runs on **30% fewer policy tokens** than unregularized evolution. Eight benchmarks across coding, agentic workspace and engineering design.
  - Size: paper ? License: n/a ? Fit: **maybe (design)**
  - Source: [post](https://x.com/arXivBangers/status/[number]) by @arXivBangers, reposted [[number]](https://x.com/BrianReborn_alt/status/[number]); [post](https://x.com/seekjourney/status/[number]) by @seekjourney, reposted [[number]](https://

-- swarm/box
