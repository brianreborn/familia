# Record soft-test accuracy with every bench and gate tuning decisions on it

Issue: https://github.com/brianreborn/familia/issues/296
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:49 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

You are to keep this response very short.

**Question:** What is the core request?  
**Answer:**  
Track soft-test accuracy across many runs, record trends, and use it to guide tuning decisions.  
**What I need:**  
- A plan for collecting data  
- Tools or steps involved  
- Risks and next steps  
- Any questions I should ask about this?

What I need is a clear, concise breakdown of the approach and what's at stake.  
I want to make sure I understand the scope before diving into code.

-- swarm/galaxy1
