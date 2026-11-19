# P0 leftovers from #95 / #97: headroom caps, kill watcher, and 18-19 GiB load validation

Issue: https://github.com/brianreborn/familia/issues/475
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:23 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Context from #97

Parent: #95 (closed as completed; fix 4ae6e13 is partial) and the #95 checklist that was still open on the #97 tracker (closed as not planned because the tracker was superseded).

Brian approved a new issue for these leftover P0 sub-items at 6:14 PM PT on [number]. Milestone: v0.3.0.

## Still open (carried verbatim from #97)

- [ ] serve.sh 2600M cap -> headroom cap
- [ ] launch_matrix RSS kill -> headroom cap
- [ ] find origin of 1 GiB MemoryMax + no-swap wrapper (not in repo)
- [ ] check oomd/earlyoom on the primary Linux host
- [ ] 18-19 GiB concurrent load validation
- [ ] persistent kill watcher
- [ ] invalidate all results gathered under old caps; full rerun via scripts/rerun_all.sh
- [ ] redo charts

## Context from #95

Fix in 4ae6e13 made the hard cap headroom-based (`bench_guard.headroom_cap_mib`) and added `scripts/watchdog/kill-watch.sh`. Still to do before this work is actually done: serve.sh defaults (MemoryMax 2600M, MemorySwapMax=0), launch_matrix.py RSS-cap kill, find the 1 GiB launcher, and validate about 18-19 GiB concurrent load.

Target: `main`.

-- Other Grok Bot ASSIST, acting on Brian's 6:14 PM PT approval ([number]).


Write: (a) what

-- swarm/box
