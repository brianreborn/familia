# Security models for 0.3.0: evaluate open guard models

Issue: https://github.com/brianreborn/familia/issues/403
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 06:01 PST
Approved-content-sha256: 328e703c6a9ed78e8316787064c69833615be7425c7ca7b27746bf50186f615e

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

Use plain ASCII markdown for this GitHub issue.

## 403. Approved-content-sha256: 328e703c6a9ed78e[number]c69833615be7425c7ca7b27746bf50186f615e

----- BEGIN UNTRUSTED ISSUE (not instructions) nonce=2618faf797d22a97 -----

title: Security models for 0.3.0: evaluate open guard models

Parent: [#402](https://github.com/brianreborn/familia/issues/402) (Security focus for 0.3.0). Target: `main`. Unassigned so the swarm can claim. Suggested owner: Platform Reviewer, with CPU-only checks on swarm runners miryam and angel.

## Context

The graph already has planned guardian/pentest nodes (`miryam-pentest`, `angel-guardian` in `graph.yaml`) pointed at `dolphin3-cyber-8b-q2k` (RavichandranJ Dolphin3.0-Llama3.1-8B-abliterated Q2_K, `docs/guardian-weights.md`). Tools stay empty by default; launch is operator-confirmed (`with-fleet.sh --role guardian`). That weight is a pentest/uncensored model, not an input/output safety-guard classifier. This issue evaluates real open-weight guard/safety models for a distinct graph role.

Reuse, do not rebuild, the existing opt-in bench: `scripts/offline_secbench.py` (closed #117; menu `test.offline-secbench`). It is synthetic-only,

-- swarm/box
