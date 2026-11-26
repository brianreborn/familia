# Alternate inference engine trials behind the Green-Roomz contract

Issue: https://github.com/brianreborn/familia/issues/778
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-26 07:59 PST
Approved-content-sha256: 9318aa4dedc2b5eb50b4a19470fb2bebba46cdfec0dec5824bbedf6882c2e5bc

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18112); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

## (a) What the issue asks

Issue #778 wants a first?pass review of **alternate inference engines** that could run behind the existing **Green?Roomz** contract. The goal is to evaluate each candidate engine (MLC LLM, ExecuTorch, vLLM, SGLang, TensorRT?LLM, and small?model options like ONNX Runtime GenAI, MNN, ncnn) while keeping the same adapter contract for the model and preserving Green?Roomz?s core behaviors (cancellation, focus?block, fan?out, ledger, etc.). The work is framed as ?alternate inference engine trials? and is meant to be done with **MLC LLM** as the Android priority and to stage each engine according to hardware fit (e.g., Android/Vulkan for A57, Qualcomm/Android for `.pte` exports, Linux accelerators for large?model batching, NVIDIA?only for TensorRT?LLM, etc.). The issue also specifies common requirements (single adapter contract, documented model format, modality support, context limits, KV?cache behavior, streaming, tool calls, quantization, hardware/backend, license) and to compare against `llama.cpp` using the same task suite, without changing Green?Roomz?s health or behavior.

---

## (b) Proposed approach & likely files / components

1. **Define a shared adapter contract** ? a single interface/ontology that does **not** mention any specific engine or model name.  
   *Likely files*:  
   - `adapter/contract.yaml` or similar (model format, modalities, context limit, KV?cache, streaming, tool calls, quantization, hardware/backend, license).  
   - Existing Green?Roomz core modules that implement the contract (e.g., `core/green_roomz.py`, `core/adapter.py`).

2. **Implement each trial engine as a plug?in** that conforms to the same adapter contract.  
   *Likely files*:  
   - `engines/mlc_llm/` ? MLC LLM integration (Android/Vulkan path).  
   - `engines/execuTorch/` ? ExecuTorch for Qualcomm/.pte export.  
   - `engines/vllm/` ? vLLM Linux accelerator path.  
   - `engines/sglang/` ? SGLang Linux path.  
   - `engines/tensorrt_llm/` ? TensorRT?LLM (NVIDIA?only).  
   - `engines/onnxruntime_mn/` ? ONNX Runtime GenAI / MNN / ncnn for small/embedded models.

3. **Bootstrap a test harness** that can run each engine on the target hardware (Android A57, Qualcomm devices, Linux servers, NVIDIA hosts) and verify:  
   - Model format & modality declarations match the contract.  
   - Context size, KV?cache behavior unchanged.  
   - Streaming, tool?call, quantization, and hardware?backend flags.

4. **Compare against `llama.cpp`** using the same task suite, ensuring identical semantics.

5. **Run functional regression tests** for Green?Roomz core features: cancellation, focus?block, fan?out, ledger behavior.

---

## (c) Risks & test ideas (no measurements ? mark as unknown)

| Risk | Why it matters | Suggested test |
|------|----------------|----------------|
| **Adapter contract drift** ? adding engine?specific fields that leak into the shared contract. | Could break ?no model or engine names in ontology?level routes?. | Verify that route definitions only reference `model_format`, `modalities`, etc., not engine names. |
| **Context?size mismatch** ? some engines may allocate different KV?cache limits. | Requirement: keep documented context sizes unchanged. | Run a short?context (e.g., 1024 tokens) and measure max context length each engine supports; compare to baseline. |
| **Streaming & tool?call differences** ? e.g., TensorRT?LLM may batch differently than vLLM. | Must preserve Green?Roomz health & protocol fidelity. | Cancel a request mid?stream, check that focus?block and ledger are updated correctly. |
| **Quantization & conversion** ? ONNX Runtime path may need model conversion. | Only for small?model/embedded use cases. | Convert the target model to ONNX, run on embedded hardware, ensure output matches llama.cpp baseline. |
| **Hardware?specific performance** ? Android/Vulkan vs. Linux vs. NVIDIA. | Each engine is staged by hardware fit. | Compile/run on A57 (Vulkan), a Qualcomm device (`.pte`), a Linux server (vLLM/SGLang), and an NVIDIA GPU (TensorRT?LLM). Record throughput & memory headroom (unknown). |
| **Crash / stability** ? new engine may have different memory usage or thread model. | Must not degrade Green?Roomz stability. | Stress test with long?running focus?block and cancellation scenarios; monitor OOM. |
| **License constraints** ? some engines may have different open?source status. | Contract includes license fields. | Check each engine?s license compatibility with Green?Roomz. |

**Test ideas (high?level)**  
- **Unit tests** for each engine?s adapter contract implementation (mock model format, modality, etc.).  
- **Integration tests** that spin up Green?Roomz with each engine and run the same task suite (e.g., tool?call, context window).  
- **Regression suite** that runs the existing Green?Roomz health checks (cancellation, focus?block, fan?out, ledger) for each trial.  
- **Benchmark script** (unknown) to collect throughput, memory headroom, and latency per engine on the listed hardware.

---

## (d) Open questions

- **Exact file layout** ? which existing files in the `familia` repo would host each engine?s implementation? (e.g., `mlc_llm/`, `execuTorch/`, etc.)  
- **Engine APIs** ? what are the current public interfaces for MLC LLM, ExecuTorch, vLLM, SGLang, TensorRT?LLM, and the small?model alternatives? Need to know if they expose a plug?in hook for the adapter contract.  
- **Hardware targets** ? specific Android device models (A57, Qualcomm, etc.) and Linux server specs (GPU type, CPU) to stage each engine.  
- **Metric definitions** ? how to measure ?correctness, crash behavior, memory headroom, protocol fidelity? (unknown).  
- **Comparison baseline** ? details of the `llama.cpp` configuration (model format, quantization, context size) to ensure identical semantics.  
- **License check** ? whether the Green?Roomz contract permits using ONNX Runtime GenAI, MNN, ncnn, or other non?LLM backends.  

*All of the above are marked as ?unknown? until the codebase and engine docs are inspected.*

-- swarm/galaxy2
