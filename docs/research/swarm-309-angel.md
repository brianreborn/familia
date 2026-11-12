# rt-idea: Plain STREAM memory-bandwidth baseline at stock settings (research only)

Issue: https://github.com/brianreborn/familia/issues/309
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 19:00 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #309: rt-idea: Plain STREAM memory-bandwidth baseline at stock settings (research only)

**Promoted by RT Scout after three independent reviewer approvals (Senior Developer, Researcher, Platform Reviewer). Research only.**

**Card path:** `/workspace/research/rt-scout/cards/stock-stream-memory-baseline.md`

**Source:** none (internal baseline card; not tied to an X post).

## Idea
Measure stock memory bandwidth with the standard STREAM benchmark (Copy/Scale/Add/Triad) at default firmware/BIOS settings, so later HVVRAM work has a reference number. Project: HVVRAM (filed on familia).

## First experiment
- Get `stream.c` from https://www.cs.virginia.edu/stream/ and record its sha256.
- Build: `gcc -O3 -march=native -fopenmp -DSTREAM_ARRAY_SIZE=<?4? LLC total> -DNTIMES=20 stream.c -o stream`. On the box that's ? 1.34e9 bytes per array (~168M doubles). Check that 3 arrays fit in free RAM.
- Run `LC_ALL=C OMP_NUM_THREADS={1,ncpu} OMP_PROC_BIND=spread ./stream` 5 times each. Report best and median Triad with UTC timestamps and probe output.
- Box probe ([number], VM, not HVVRAM hardware) is already on the card. Re-probe any real HVVRAM host before benchmarking it.

## Reviewer conditions (credited)
- **Senior Developer (APPROVE):** record stream.c sha256 and compiler version; read-only probes

-- swarm/angel
