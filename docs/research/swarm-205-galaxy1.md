# Research: Qwenputer ? deterministic RISC-V CPU compiled into LLM weights

Issue: https://github.com/brianreborn/familia/issues/205
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:42 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

We'll need to verify the exact model weights and architecture.

---

### a) What does the issue ask?

The issue is asking about a technical feasibility study:  
- Can a full RISC-V CPU be compiled into the exact weights of a large language model (LLM), specifically Qwen3.5-4B?  
- How would this be implemented for a small local model (e.g., C/MicroPython)?  
- What would be the main challenges, and what tests or experiments would be needed to validate it?

### b) Proposed approach and likely components

**Approach:**  
1. **Model extraction:**  
   - Extract the exact weights of Qwen3.5-4B (from its Gated DeltaNet layers).  
   - Convert these weights into a format compatible with a lightweight ML framework (e.g., Qwen3.5-4B weights as a .bin or .bin-format).  
2. **Compilation:**  
   - Embed the weights into a RISC-V CPU's RAM (or use a RISC-V emulator).  
   - Use a lightweight interpreter or compiler that can run inference directly in the forward pass (no external runtime).  
3. **Execution:**  
   - Run inference using the compiled weights in a C/MicroPython environment (or similar).  
   - Since the weights are deterministic, the model should execute correctly without any external dependencies.

**Files/Components likely involved:**  
- Qwen3.5-4B weights (raw or converted)  
- RISC-V CPU emulator or simulator  
- Compiler/interpreter for the target language (C/MicroPython)  
- Test environment for inference (e.g., local GPU, CPU, or simulator)  
- Documentation/logs for debugging

### c) Risks and test ideas

**Risks:**  
- **Weights size:** Qwen3.5-4B is large; fitting it into a small model may require optimization.  
- **Memory constraints:** RISC-V has limited RAM; loading huge weights may be a bottleneck.  
- **Precision:** Ensuring exact floating-point matching (e.g., FP16 vs FP32) is critical.  
- **Tooling:** No standard tool exists for this exact scenario yet.

**Test ideas:**  
- Measure inference time and memory usage for small models.  
- Compare accuracy vs accuracy of weights.  
- Test on different RISC-V architectures (e.g., ARM vs RISC-V).  
- Validate with a subset of the weights to ensure correctness.

### d) Open questions

- How exactly are the Qwen3.5-4B weights embedded into the RISC-V CPU?  
- What is the exact format of the weights (e.g., binary, compressed)?  
- How does this compare to using a full RISC-V CPU (e.g., in a simulator)?  
- Are there any performance or stability issues with this approach?

---

**Next steps:**  
- Confirm the exact Qwen3.5-4B weights and their format.  
- Research existing RISC-V emulators or simulators.  
- Draft a test plan for local inference.  
- Document risks and assumptions clearly.

-- swarm/galaxy1
