# Small-model research follow-ups: fill unknown memory for TTS/diarization/vision/imagegen

Issue: https://github.com/brianreborn/familia/issues/47
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:59 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

And mention the relevant GitHub issues.

---

### **Delivered**

I'm working on a short first-pass research note for the **familia project**. Here's what I'm covering:

#### **What's the issue asking?**
- We need to **fill gaps in memory** for various research tasks: translation, TTS, diarization, vision (image generation), and image generation with text.
- The goal is to **understand what's missing** and what we should test next.

#### **Proposed approach**
- **Check what we already have** (e.g., model weights, runtimes, licenses).
- **Propose experiments** to clarify unknowns:
  - **Translation**: Test on more data to see if models generalize.
  - **TTS**: Run on different models to see if quality improves.
  - **Diarization**: Use multiple models to see if they agree.
  - **Vision**: Compare real vs. predicted images.
  - **Image generation**: Measure performance with and without text prompts.
- **Risks**: Some models may not support certain formats or runtimes.
- **Test ideas**: Small experiments with limited resources (e.g., CPU only, limited GPU time).

#### **Open questions**
- Are there specific datasets missing?
- Do any models have licensing issues?
- How do we handle missing data formats?

#### **GitHub issues referenced**
- **#25 (Whistle/Paradee)** ? likely related to model selection.
- **#24 (decision catalog)** ? possibly about evaluation metrics.

Let me know if you want me to expand any section or add more details!

-- swarm/galaxy1
