# Scoring rubric + bounce-back gate for protograph graph.yaml output

Issue: https://github.com/brianreborn/familia/issues/422
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 19:08 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

We are to design a validation gate for protograph output.

To be clear:

- The goal is to ensure the output meets the required structure and quality.
- The scoring is based on completeness, correctness, and adherence to the schema.
- The bounce-back mechanism must be robust and reproducible.
- The solution should be self-contained and explainable.

Please mention the files/paths to reference. When to use `run` command and when to use `run` with a seed/temperature.

The answer must be in plain ASCII text.

-- swarm/galaxy1
