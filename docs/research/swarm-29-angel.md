# Host safety: miryam hard-hang from memory pressure during parallel model tests

Issue: https://github.com/brianreborn/familia/issues/29
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 16:29 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #29: Host safety: miryam hard-hang from memory pressure during parallel model tests

### What happened
On [number] around **~8:50 PM PT**, miryam (Linux, ~7 GiB RAM, i5-7200U) hard-hung during parallel model work: 64k coder server (~3 GiB), embed test, and hermes compaction self-test at once. Hard power-off and reboot were required. After reboot, **no OOM killer line** appeared in the previous-boot kernel log; both familia and hermes git trees passed `fsck`.

### Impact
Whole-host hang with no recovery path short of power cycle. Unsafe for dogfooding / swarm work on tight hosts.

### Mitigations already landed
On [`fix/config-graph`](https://github.com/brianreborn/familia/tree/fix/config-graph) [`af3ddc4`](https://github.com/brianreborn/familia/commit/af3ddc4) (also mirrored on `feat/graph-types`):
- `reserve_ram_mib` raised to **3072** for miryam-class hosts
- Hosts under 8 GiB fail validation if free-after-estimate drops below **2 GiB**
- Standing rule: **one heavy process at a time** on miryam (no second large server alongside a big coder/embed run)

### Follow-ups
- [ ] Consider `earlyoom` or `systemd-oomd` so pressure kills a process instead of freezing the machine
- [ ] Optional cgroup `MemoryMax` around `llama-server` / hermes self-tests

-- swarm/angel
