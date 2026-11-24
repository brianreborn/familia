# Survey (Sep?Oct 2026): Models ? small/edge & ternary LLMs

Issue: https://github.com/brianreborn/familia/issues/54
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:04 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

Also, keep it short and focused on the *first pass* for the story.

---

# Summary

We?re asking whether **smaller, quantized LLMs** (especially ternary or 2B/4B models) can be
deployed as light "family" agents?small enough to run on edge hardware. The key
questions are:
- Which models actually fit the target hardware budget?
- What?s the best way to test their performance on the target use-case?
- What are the biggest unknowns or risks?

**Files/Components likely involved:**
- [Ternary Bonsai 2](https://huggingface.co/prism-ml/Ternary-Bonsai-2-2B-gguf) ? likely the closest match.
- [PrismML](https://huggingface.co/prism-ml) ? the upstream repo for fine-tuned models.
- [mmproj](https://github.com/yh-dwm/mmproj) ? for loading and inference.
- [HuggingFace API](https://huggingface.co/api) ? for checking repo links and model weights.
- [Bonsai-2-27B](https://huggingface.co/dealignai/Bonsai-2-27B-1bit-CRACK-GGUF) ? a reference for size and licensing.

**Open questions:**
- How will you verify if the models can run on the target hardware?
- What metrics will you use to evaluate "family" performance?
- Are there any licensing or provenance issues you need to address?

This is a **first-pass**?we?re narrowing down the options and planning next steps.

**Next steps:**  
1. Check the exact repo URLs and model weights from the public APIs.
2. Run a quick test on a small dataset to estimate feasibility.
3. Document risks (e.g., license, inference speed, accuracy).

Let me know if you want a deeper dive on any of the models or steps!

-- swarm/galaxy1
