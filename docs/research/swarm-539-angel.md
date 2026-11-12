# Benchmark: wholesale KV ship vs text-summary handoff (SwaT comparison)

Issue: https://github.com/brianreborn/familia/issues/539
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 21:08 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Goal

Measure Familia **Stage 1** wholesale KV shipping against a text-summary handoff baseline. This is the first empirical step that stays on the capability we already ship: we do not transform between models; we ship memory wholesale when the runtimes match. Nothing in this issue trains or vendors a cross-family mapper.

## How this differs from SwaT and C2C

Familia Stage 1 is **one step less** than SwaT/C2C: same-model slot KV, no learned transform, refuse the ship unless build/ctx/GGUF sha256/KV dtype match.

| | Familia Stage 1 (this benchmark) | C2C | SwaT |
|---|---|---|---|
| Payload | Same-model llama.cpp slot KV file | Fused/mapped KV | Mapped KV |
| Cross-family transform | No | Yes (learned fuser) | Yes (~300M mapper) |
| Receiver doc prefill | Skipped for the saved prefix | Still needed (SwaT Table 1) | Claimed skipped |

SwaT (arXiv [2610.15095](https://arxiv.org/abs/2610.15095), MIT CSAIL / MIT-IBM; code [Ar-Kareem/SwaT](https://github.com/Ar-Kareem/SwaT)) and C2C (arXiv [2510.03215](https://arxiv.org/abs/2510.03215), [thu-nics/C2C](https://github.com

-- swarm/angel
