# P1: AirLLM layer-at-a-time loading for low-VRAM GPUs

Issue: https://github.com/brianreborn/familia/issues/90
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:34 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

You must include the reference number in your answer.
You must include the reference number in your answer.

The issue asks about optimizing the AirLLM layer-streaming
approach for low-VRAM GPUs. Specifically, it wants to know how to make the planner
choose a suitable loading mode and how to test it.

**Answer:**

**a) What the issue asks:**  
The issue is about improving the AirLLM (Air Language Model Loader)  
performance on low-VRAM GPUs by selecting an appropriate loading mode  
(like layer-streaming) and verifying it works well with both the planner
and the topology bandwidth prototype.

**b) Proposed approach:**  
We need to evaluate how the AirLLM can be loaded in a way that fits  
the constraints of low-VRAM GPUs?likely by using a per-layer streaming
mode that reduces memory pressure. This would involve checking how the
planner selects the right mode and how it impacts model loading speed.
We?d likely test this on the CentOS box (legacy GPU + CPU) and the
phone where relevant, comparing actual performance against measured
benchmarks.

**c) Risks and test ideas:**  
Risks include inaccurate layer selection, misalignment with the
planner?s topology, or insufficient memory bandwidth. To test, we could
run simulations that vary the loading mode and measure how well the
model loads. Open questions involve understanding how the planner?s
decisions are influenced by GPU memory limits and how to validate
that the chosen mode meets the 30% speed target.

**d) Open questions:**  
- How does the planner decide which loading mode to use?  
- What are the exact performance differences between layer-streaming and
  other modes on low-VRAM hardware?  
- Can we confirm that the selected mode meets the speed target without
  extensive manual tuning?

Reference: #90

-- swarm/galaxy1
