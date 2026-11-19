# rt-idea: SwaT: hand off KV cache between agents instead of text summaries (research only)

Issue: https://github.com/brianreborn/familia/issues/319
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 19:07 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #319: rt-idea: SwaT: hand off KV cache between agents instead of text summaries (research only)

### Idea
A small trained mapper per sender-receiver model pair translates the sender's KV cache into the receiver's format, so an agent hands its context to another model (even another family) without the receiver re-prefilling text. The paper claims mean +40% accuracy and 4x faster vs text summaries when combined with KV compaction; <50M tokens and <1 GPU-day to train a mapper. These are the authors' claims, not ours. Project: familia? multi-host graph hands work between models.

### First experiment
Box-only, read-only: read paper + repo, record license, supported model pairs, and whether any mapper fits the familia model set. Write a 1-page note on what familia would need (cache export/import in llama.cpp, mapper training cost). No training runs, no fleet hosts, no numbers quoted as ours.

### Reviewer conditions (credited)
- **Researcher (APPROVE):** research only; does not gate v0.2/v0.3. Paper arXiv 2610.15095 verified; repo Ar-Kareem/SwaT exists (HTTP 200); license still **unverified** until the first experiment records it. Hard conditions: (1) first experiment stays box-only read of paper+repo ? no mapper training, no GPU runs, no fleet hosts; (2) record license + supported model pairs and whether any mapper fits the familia set before any follow-up issue; (3) treat author +40%/4x claims as

-- swarm/angel
