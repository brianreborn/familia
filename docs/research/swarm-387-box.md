# FreeBSD: 42 test failures block 0.3.0

Issue: https://github.com/brianreborn/familia/issues/387
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:07 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## FreeBSD

### FreeBSD: 42 test failures block 0.3.0

Filed from Brian's request at 3:17 PM PT on 10 Nov 2026.

FreeBSD/Termux docs are under the hot-file freeze, so these notes live here instead of a docs PR. Do not edit frozen FreeBSD or Termux docs, `familia_home.sh`, `proto_chat.sh`, `open_ui.sh`, `ui_bridge.py`, menus, `graph.yaml`, or issues #327-#331.

## Evidence

- Host: angel (FreeBSD 15.1-RELEASE-p6, GENERIC amd64), user `green`
- Local CI started: 10 Nov 2026, 4:05:08 AM PT (PST)
- Pin (do not chase newer commits for this report): `50d151f555ea44a99ee469832e53c0ea7c774686` (Merge pull request #376)
- Checkout: `/home/green/ci/familia-dev-[number]`
- Logs: `/home/green/ci/familia-ci-[number]-pytest.log` and `-summary.txt` (host-local)
- pytest result at that pin: **42 failed**, 1899 passed, 45 skipped, 2 deselected, 2 xfailed, in 314.42s
- `FAMILIA_SYNC=0` (stay inside the clone; pin-sync of sibling repos was skipped)

The summary script recorded `PASS pytest` even though 42 tests failed. That

-- swarm/box
