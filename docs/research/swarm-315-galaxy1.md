# Research: Hermes Office 3D - watch agents as 3D office avatars

Issue: https://github.com/brianreborn/familia/issues/315
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:59 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

)
**What is the core question?**
- Are we just rendering avatars or integrating them into a workflow?
- What's the value of showing agents in 3D space?
- What's the difference between a "fleet" and a "visual" view?
- What are the risks?

**Proposed approach**
- Build a small demo with a 3D office scene.
- Test agent placement, navigation, and interaction.
- Compare with a flat 2D view.

**Files/Components**
- Office 3D engine (e.g., Unity, Unreal, or a custom scene).
- Agent scripting (movement, interaction).
- UI for agent placement.

**Risks**
- Performance with many agents.
- UI/UX for navigation.
- Integration with existing workflows.

**Open questions**
- How to scale this?
- How to integrate with other tools?

---

**Final note:**  
This is a research-focused task. No actual code or data is used?just analysis.  
Let me know if you want a more detailed breakdown or a mockup of the demo.

-- swarm/galaxy1
