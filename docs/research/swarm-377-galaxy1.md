# X-interaction intake: doc/tracker inconsistencies (ideas-from-x skill)

Issue: https://github.com/brianreborn/familia/issues/377
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 19:06 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

Also note: the issue is not a bug in the `README.md` or `skills.md`,
but a documentation inconsistency that needs clarification.

---

**What I need to do:**  
- Verify the exact text in `skills/README.md` and `docs/skills.md`.  
- Identify which files and sections are affected.  
- Propose a safe, incremental fix (e.g., updating the README line).  
- List risks, test steps, and open questions.  
- Flag what?s missing (e.g., HVVRAM, labels, etc.).  
- Keep the tone professional and concise.

-- swarm/galaxy1
