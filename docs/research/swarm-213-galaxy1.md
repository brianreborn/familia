# Research: Safe parallel coding agents (multi-agent-repo-protocol)

Issue: https://github.com/brianreborn/familia/issues/213
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:48 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

We'll need to check if this is a known issue and if it's worth pursuing.

---

Let's break this down in plain English and markdown.

### 1. What is the issue asking?

We're dealing with a Git workflow where multiple "agents" (like workers or branches) are working on the same codebase.  
Some agents are trying to delete each other's uncommitted changes (parallel coding agents).  
We need to **prevent** this from breaking the local diff or causing conflicts.

### 2. Proposed approach

- **Per-agent worktree:** Each agent has its own Git worktree.
- **Claims table:** A table to track what each agent has been working on.
- **Agent commit trailer:** A mechanism to ensure that an agent always commits before it can delete another agent's work.
- **Enforced checks:** When an agent tries to delete another's uncommitted work, it must pass a check.

### 3. Risks and test ideas

- **Conflict:** Two agents deleting each other's work could corrupt the diff.
- **Performance:** More worktrees and claims may slow down the repo.
- **Testing:** Need tests to simulate concurrent edits and verify that the system prevents corruption.

### 4. Open questions

- How to detect and prevent deletion of uncommitted work.
- How to implement the claims table and trailer.
- How to integrate this with the existing `familya` workflow.
- Are there existing solutions or tools we can adapt?

### 5. What to do next

- Check if this is a known issue on GitHub.
- If not, we can start prototyping the solution.
- If it is, we can assess the effort needed and if it aligns with our goals.

---

**Final note:** This is a high-level plan. We'll need to validate the idea with the team and see if it fits our current roadmap.

Let me know if you want to expand any section or add more details.

-- swarm/galaxy1
