# RT idea (HVVRAM): file-backed sparse read-only table, fetch only the rows each token needs

Issue: https://github.com/brianreborn/familia/issues/298
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:51 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

---

# Leave a huge read-only lookup table on disk and fetch only the rows each token needs

- **Source (Brian's repost):** https://x.com/i/status/[number]
- **Original post:** https://x.com/i/status/[number] (@TeksEdge)
- **Brian's follow-up asking how it fits HVVRAM:** https://x.com/i/status/[number] (Grok replies: https://x.com/i/status/[number] and https://x.com/i/status/[number])
- **Quote from post:** "Now it can leave the table inside the original safetensors files. ... only those rows are fetched ... So the entire 51B table never has to become resident in VRAM or pinned RAM." Contributor-reported on one DGX Spark: "99.09 ? 72.09 GiB loaded memory", "decode within ~3.5% at c=1", cold rows raise time-to-first-token slightly.

## Core idea
Some model parts (here a 51B-parameter n-gram lookup table) are read-only and only a few rows are touched per token. Instead of loading the whole thing into GPU or pinned RAM, keep it file-backed, read just the needed rows, and let the OS page cache hold the hot ones (reclaimable memory).

## Project
HVVRAM ? a concrete, narrow use case for the storage-backed tier: a mostly-static, sparse, read-only structure where full coherence machinery isn't needed. Brian explicitly asked whether this fits HVVRAM, so it has his interest. Also relevant to familia RAM-safety on small hosts.

## Effort & risk
Low-medium

-- swarm/box
