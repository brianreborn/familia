# FreeBSD: missing registry/llama-builds flag tables under FAMILIA_SYNC=0

Issue: https://github.com/brianreborn/familia/issues/391
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:08 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

## Write

- **Issue #391**: FreeBSD: missing registry/llama-builds flag tables under FAMILIA_SYNC=0

Parent: #387 (FreeBSD: 42 test failures block 0.3.0).

This is one category covering both of the following, which failed with the same error (not a separate ram-floor logic bug):

- `tests/test_graph_types.py::test_ram_safety_reserve_and_small_host_floor`
- `tests/test_ram_safety.py::test_small_host_free_floor`

## Evidence

- angel, FreeBSD 15.1, pin `50d151f`, `FAMILIA_SYNC=0`
- pytest `--tb=line` excerpt:

```
AssertionError: ['nodes.phone7-decision: runtime termux-llama-cpp-0.6.0: no flag table (registry/llama-builds), flag support is unverified',
'nodes.angel-chat: runtime llama-b11669-freebsd: no flag table (registry/llama-builds), flag support is unverified', ...]
```

Line refs: `tests/test_graph_types.py:444` and `tests/test_ram_safety.py:61`.

The morning script skipped pin-sync on purpose (`FAMILIA_SYNC=0; stay inside the clone folder`), so sibling `registry/llama-builds` content was not fetched.

## Suspected cause

These tests (or the graph they load) require flag tables from `registry/llama-builds`. With `FAMILIA_SYNC=0` those tables are missing, so

-- swarm/box
