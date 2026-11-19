# Integrate Cache-to-Cache (C2C) KV-cache exchange as a graph edge and transport

Issue: https://github.com/brianreborn/familia/issues/22
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:42 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Background: Cache-to-Cache (C2C)
- Paper: "Cache-to-Cache: Direct Semantic Communication Between Large Language Models" (Fu et al.), https://arxiv.org/abs/2510.03215
- Code: https://github.com/thu-nics/C2C (ICLR'26 official implementation)

C2C uses a learned fuser to project the frozen Sharer model's KV cache into the Receiver model's cache space and add it to the Receiver's own cache (residual connection, with a learnable gate on each layer). The two models never exchange text. Only the fuser is trained; both LLMs stay frozen. Tokens are aligned by decoding and re-encoding, and layers are aligned from the last layer backward.

Results reported in the paper abstract:
- 6.4?14.2% higher average accuracy than either model alone
- about 3.1?5.4% higher than models exchanging text
- about 2.5? lower average latency

Posts about C2C quote slightly different numbers (~8.5?10.5%, ~3?5%, ~2?). Only the paper's figures are cited here.

Paper experiments use small pairs (Qwen3-0.6B, Qwen2.5-0.5B, Llama3.2-1B, Gemma3-1B). A pair's fuser reaches near-final accuracy in about 300 steps (under 9 GPU hours). The paper also covers one Receiver with several Sharers, and a shared-latent design that needs O(N) fusers instead of O(N?).

-- swarm/angel
