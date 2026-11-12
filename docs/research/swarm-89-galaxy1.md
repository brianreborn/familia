# P1: Jev harness-building guide for prompt/harness slimming

Issue: https://github.com/brianreborn/familia/issues/89
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:32 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

If you have a preferred format for the answer, please specify.

I need this in plain ASCII markdown, so I can copy-paste it directly. Here's my draft:

---

### [Your Name]  
[Your Contact Info]  
[Date]

#### Issue #89: P1 ? Jev Harness-Building Guide for Prompt & Harness Slimming

**What the issue asks:**  
The team is looking to improve the Jev harness-building process, specifically focusing on how to make the prompt and harness slimming more effective. They want to ensure the changes are practical, measurable, and tested across different models (Hermes and Harness).

**Proposed approach:**  
- Review the Jev harness-building guide (PDF) to identify the main steps and parameters.
- Identify which parts of the guide are critical for slimming (e.g., weight files, model selection).
- Update the build scripts or configuration files to apply the recommended slimming changes.
- Test the updated process on both Hermes and Harness models to confirm improvements.

**Risks and test ideas:**  
- Potential risk: Changes may not apply correctly to all models.
- Test idea: Compare slimming results before and after changes on a sample of models.
- Open question: Are the new slimming parameters compatible with existing build pipelines?

**Open questions:**  
- How do we ensure the changes are consistent across different build environments?
- What are the exact parameters that need updating for slimming?

---

Let me know if you want this adjusted or expanded further.

-- swarm/galaxy1
