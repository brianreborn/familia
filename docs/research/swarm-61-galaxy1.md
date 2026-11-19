# Survey (Sep?Oct 2026): Research ? training methods & optimization

Issue: https://github.com/brianreborn/familia/issues/61
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:15 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

And end with a clear "**Next steps**" and a single bolded action item.

---

**Final response:**

We?re investigating how to optimize training and model behavior?specifically around hallucination risks and reward calibration. The key gaps are:

- **Semantic calibration** (Apple?s claim about RLHF) ? no verifiable paper or repo matches.
- **Forward-forward / bio learning** ? no evidence of a published paper; only a threaded discussion.
- **Hinton?s perspective** ? historical context, but no direct link to this issue.
- **Thermodynamic computing** ? a paper on image generation without a neural net was flagged as unrelated.

**Proposed approach:**  
We should design a controlled experiment comparing different RLHF strategies (e.g., RLHF vs bio-inspired) using synthetic data and analyze hallucination rates. We?ll need access to training logs, reward models, and possibly a small dataset of model outputs for analysis.

**Risks:**  
- Overfitting to noisy signals (e.g., hallucinations).
- Inaccurate attribution of claims to sources.
- Difficulty isolating variables due to open-source dependencies.

**Test ideas:**  
- Compare model outputs under different RLHF settings.
- Audit hallucination rates with human evaluation.
- Investigate if local-minima history affects training stability.

**Open questions:**  
- How do we reliably detect and mitigate hallucinations in RLHF?
- What is the true cost of "optimization" in large models?

**Next steps:**  
We need to secure a source for the Apple RLHF claim and clarify the paper link before moving forward.

**Next action:** Confirm the source of the Apple RLHF claim and obtain the associated paper or repo.

-- swarm/galaxy1
