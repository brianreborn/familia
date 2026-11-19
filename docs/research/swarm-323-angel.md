# Proposal: FreeBSD Resource Limits & RACCT/RCTL Integration for AGY Workloads

Issue: https://github.com/brianreborn/familia/issues/323
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:02 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

### Summary

The issue #323 proposes integrating FreeBSD resource limits and RACCT/RCTL for AGY workloads on FreeBSD. The goal is to prevent runaway resource usage and ensure system stability without relying on brittle cgroup dependencies.

### Context & Problem

- Antigravity (AGY) and other intensive agentic workloads may attempt to allocate address space based on Linux defaults.
- Setting `ulimit -v` on FreeBSD is counterproductive and brittle because FreeBSD enforces address space limits strictly via immediate `SIGKILL`.
- Uncapped stack sizes and unbounded data segments allow runaways before system triggers catch them.

### Proposed Solution

A two-tiered native FreeBSD resource management approach:

#### 1. Shell & Process Soft Limits (`~/.profile` / `agy-limits.sh`)
Hardware-aware dynamic bounds calculated from `hw.physmem`:
- **Data Segment (`-d` / `RLIMIT_DATA`)**: Capped at ~80% of total physical RAM to prevent runaway heap allocations while allowing normal runtime operations.
- **Resident Set Size (`-m` / `RLIMIT_RSS`)**: Capped at ~75% of physical RAM.
- **Stack Size (`-s` / `RLIMIT_STACK`)**: Capped at 256MB per thread/stack to prevent unbounded recursive or thread-stack blowups.
- **File Descriptors (`-n` / `RLIMIT_NOFILE`)**: Set to a generous default of 4096.

#### 2. Kernel-Level Enforcement via RACCT / `rctl(8)`
Enforce aggregate resource limits per-user across all child processes spawned by AGY:
- **Kernel

-- swarm/angel
