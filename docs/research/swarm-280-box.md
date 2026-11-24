# Handoff 5/8 (Team A ? Team B): familia merge queue (v2, b041fb8, wire, #251, routing, Continuity, d646511)

Issue: https://github.com/brianreborn/familia/issues/280
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:21 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

## #169 `swarm/race/miryam-perf`, #170 `swarm/race/specdec-91`
- **HOLD** (fix-forward) until `fix-forward` is done. `fix-forward` is a separate issue in brianreborn/green-roomz. `swarm/race/miryam-perf` is a test case in `swarm/race/` and `specdec-91` is a test case in `swarm/race/`.

## #170 `swarm/race/specdec-91`
- **HOLD** (fix-forward) until `fix-forward` is done. `fix-forward` is a separate issue in brianreborn/green-roomz. `swarm/race/specdec-91` is a test case in `swarm/race/`.

## #169 `swarm/race/miryam-perf`, #170 `swarm/race/specdec-91`
- **HOLD** (fix-forward) until `fix-forward` is done. `fix-forward` is a separate issue in brianreborn/green-roomz. `swarm/race/miryam-perf` is a test case in `swarm/race/` and `specdec-91` is a test case in `swarm/race/`.

## #169 `swarm/race/miryam-perf`, #170 `swarm/race/specdec-91`
- **HOLD** (fix-forward) until `fix-forward` is done. `fix-forward` is a separate issue in b

-- swarm/box
