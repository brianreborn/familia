# Verify Vulkan -ngl 0 shmem fix (GGML_VK_VISIBLE_DEVICES=) on miryam

Issue: https://github.com/brianreborn/familia/issues/40
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:24 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

## Write
- (a) What is the issue asking? In plain English, what is the problem with
Vulkan llama-server building with `-ngl 0`? (i.e., why is it allocating ~1.8 GB
host buffers in shmem even when gpu-layers is 0?)
- (b) Proposed approach: How would you fix it? (i.e., make it allocate ~1.2 GB
instead of ~1.8 GB, or at least not bloat memory.high events). Suggest the files or
components likely involved. (i.e., `serve.sh`, `validate_graph.server_env`, etc.)
- (c) Risks and test ideas: What could go wrong? How would you test it? (i.e., empty
env vars, RSS/shmem, memory.high events, health).
- (d) Open questions: Anything you don't know or need clarification? (i.e., does the
env var need to be exported by the user, or is it enough for the coder to have it set?)

Write in plain ASCII markdown for a GitHub issue.</think>## Write

- **(a) What is the issue asking?**  
  In plain English, why does building `Vulkan llama-server` with `-ngl 0` allocate ~1.8?GB host buffers in shmem even though the Vulkan runtime is set to `GGML_VK_VISIBLE_DEVICES=` (empty)? This bloat stalls the coder (memory.high thrash / health events). The fix landed on `code-bootstraps-llama.cpp 4c29edd`

-- swarm/box
