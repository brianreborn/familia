# Research: Image-in-context priming changes coding style (DeepMind/Stanford)

Issue: https://github.com/brianreborn/familia/issues/207
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:44 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

Explain your thought process in a few sentences.
Why is this a good first-pass for a family?
---

**Answer:**

We?re investigating how context?like an image or prior conversation?affects a model?s behavior. The paper shows that even irrelevant details can steer code generation, suggesting we need to audit what the model passes along. We should design tests that simulate different contexts and see if they change output. This helps ensure the family?s routing logic stays consistent, even with unexpected inputs.

**Files/Components:**  
- Model training data  
- Contextual prompts (e.g., images, logs)  
- Evaluation scripts  
- Model versioning (v0.2, v0.3)

**Risks:**  
- Overfitting to irrelevant context  
- Inconsistent behavior across runs  

**Test ideas:**  
- Add controlled context variables  
- Compare outputs with/without context  
- Monitor model logs for anomalies  

**Open questions:**  
- What context cues truly matter?  
- How do we detect and correct for them?  

This is a good first-pass because it frames the problem clearly and guides our testing without assuming results.

-- swarm/galaxy1
