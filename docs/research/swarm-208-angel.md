# Research: Diffusion LLMs (Clover-35B-A3B dLLM)

Issue: https://github.com/brianreborn/familia/issues/208
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:47 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #208: Research: Diffusion LLMs (Clover-35B-A3B dLLM)

## Issue Description
The issue asks for research into diffusion LLMs, specifically focusing on the Clover-35B-A3B dLLM released by DiffuSpace. The goal is to evaluate whether llama.cpp's diffusion support can run this model and whether it fits as a fast drafter or bulk-generation worker in the graph.

## Proposed Approach
1. **Understand the Clover-35B-A3B dLLM:**
   - Review the model's architecture, capabilities, and performance metrics.
   - Understand the diffusion process and how it differs from traditional language models.

2. **Evaluate llama.cpp's Diffusion Support:**
   - Test llama.cpp to see if it can run the Clover-35B-A3B dLLM.
   - Analyze the performance of llama.cpp in terms of speed, memory usage, and stability.

3. **Assess the Model's Suitability for Drafting and Bulk Generation:**
   - Evaluate whether the Clover-35B-A3B dLLM is suitable for real-time drafting tasks.
   - Assess its performance in generating large volumes of text.

4. **Document the Findings:**
   - Compile a report detailing the evaluation results.
   - Include any limitations or challenges encountered during the testing process.

## Files or Components Involved
- llama.cpp: The diffusion support library for llama models.
- Clover-35B-A3B dLLM: The model to be evaluated.
- Performance metrics: Speed, memory usage, and stability.

## Risks
- Technical challenges in running the

-- swarm/angel
