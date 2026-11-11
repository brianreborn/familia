# Tuning: opt-in relax/disable OOM killers per platform, replaced by proper soft limits

Issue: https://github.com/brianreborn/familia/issues/295
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:49 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Live probe: miryam, [number] ~07:37 PT (read-only, nothing changed)
- `systemd-oomd.service` and `.socket` are **active** (unit disabled, socket-activated). oomctl: swap-used limit 90%, memory-pressure limit 60% for 20s. `user.slice` has ManagedOOMSwap=auto and ManagedOOMMemoryPressure=auto. User-level oomd is inactive.
- earlyoom is installed but inactive and disabled. nohang is not installed.
- Kernel: `vm.overcommit_memory=0`, `vm.panic_on_oom=0`, `vm.oom_kill_allocating_task=0`, `vm.swappiness=60`.
- llama-server (gemma :8303): `oom_score_adj=100`, `oom_score=785`. It runs in `app-grok-bot-*.scope`, so it's the **first kernel OOM victim**.
- Swap: zram0 1.8G (prio 100), /swapfile 4G, sda3 16M. RAM is 7.1G with about 4.5G available.
- cgroups: `user.slice` memory.high/max = max and MemoryHigh/MemoryMax = infinity, so **no soft limits exist**. Hard killers are the only protection.

## Scope (per platform, opt-in knobs)
- **Linux:** systemd-oomd (mask, or set per-slice ManagedOOM*=kill?auto/none, or raise thresholds), earlyoom/nohang (stop/disable

-- swarm/box
