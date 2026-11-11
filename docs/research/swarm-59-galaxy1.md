# Survey (Sep?Oct 2026): Engines ? agent frameworks & harnesses

Issue: https://github.com/brianreborn/familia/issues/59
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:11 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

I'll be careful with the numbers.

---

**Final note:**  
The issue is about running an *engine* (agent) in a constrained, real-world scenario?likely a mobile device or embedded system. The key is to pick a lightweight, fast, and flexible framework that can handle the model?s inference and interaction with hardware.

**Proposed approach:**  
- Use **OpenDots** or **OpenClaw** (both lightweight, MIT-licensed, good for phone hardware).  
- **Harness** (e.g., DeepSeek Harness) for natural-language to Android automation.  
- **Agent-Reach** or **Hindsight** for more advanced inference.  
- **GoClaw** could be a good fit for a minimal, self-hosted agent with fast startup.

**Risks:**  
- Model size may be too large for some devices.  
- Dependency on network access for model loading.  
- Hardware/software compatibility (especially for older devices).

**Test ideas:**  
- Test on a Raspberry Pi with a 4GB RAM model.  
- Validate with a small dataset to ensure inference latency < 1s.  
- Check if the agent can handle basic prompts (e.g., "summarize this").

**Open questions:**  
- How to measure actual inference time on real hardware?  
- Can we guarantee the agent will not crash on a device with limited RAM?  
- What?s the best way to verify the agent?s behavior?

Let me know if you want me to expand any section or add more details.

-- swarm/galaxy1
