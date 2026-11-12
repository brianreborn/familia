# Evaluate Qwen3.5 9B GGUF (Kimi-k3 distill) as a local coder candidate

Issue: https://github.com/brianreborn/familia/issues/26
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:51 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #26: Evaluate Qwen3.5 9B GGUF (Kimi-k3 distill) as a local coder candidate

From the #20 classification: https://github.com/brianreborn/familia/issues/20#issuecomment-[number] (bucket 2)

Source: https://x.com/BrianReborn_alt/status/[number] (@HuggingModels)

## Notes
- miryam (7 GB, 3 GB reserve) can't fit a 9B model alongside anything else. qodesh (16 GB, CPU only, about 11.5 GB free) is the likely host.
- Compare against the current coder on a small coding slice.

## Tasks
- [ ] Resolve the repo and choose a quant
- [ ] Add the catalog entry; validator RAM check
- [ ] Measure tok/s and quality on qodesh

## Proposed Approach
1. **Resolve the Repo and Choose a Quant:**
   - Identify the exact HF repo for Qwen3.5 9B GGUF (Kimi-k3 distill).
   - Determine the appropriate quantization method (e.g., GPTQ, QLoRA, etc.) to reduce the model size and improve performance.

2. **Add the Catalog Entry:**
   - Create a new entry in the family project's catalog for the Qwen3.5 9B GGUF (Kimi-k3 distill) model.
   - Include details such as model size, quantization method, and any other relevant information.

3. **Validator RAM Check:**
   - Ensure that the validator (or any other system) has enough RAM to accommodate the

-- swarm/angel
