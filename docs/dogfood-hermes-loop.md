# Dogfood hermes / Harness² loop adapters (#110)

Owned on branch `swarm/hermes/dogfood-110` (Hermes Wiring). Gum home /
Continuity front door are out of scope.

## Modules

| module | role |
|---|---|
| `scripts/dogfood/hermes_loop.py` | Real hermes **single** + **graph** loops: `hermes.sh --render-only`, then `hermes-agent -z` in the task worktree |
| `scripts/dogfood/harness2_loop.py` | Real Harness² `propose` via `scripts/harness2.py` |
| `scripts/dogfood/dispatch.py` | Orchestrator: worktree, admission, big.lock, accept rates → `dogfood-daily.md` |

## Hermes API (importable)

```python
from hermes_loop import (
    TOOLSETS, HARNESS_TO_MODE,
    build_render_cmd, build_agent_cmd, home_for,
    run_render, run_oneshot, smoke_ok, resolve_agent_bin, agent_env,
)
```

- Tools: `file,terminal,todo` only (no web/search/browser).
- Binary: `hermes_harness.resolve_hermes` (snap / FreeBSD ports / `HERMES_BIN`).
- Child env: `hermes_harness.hermes_child_env` (+ `FAMILIA_SYNC=0`).
- Live servers: `DETACH_MODE=screen-attached` via `serve.sh` when `--start-node`.

## Harness² API

```python
from harness2_loop import build_propose_cmd, run_propose, propose_accepted
```

Smoke uses `--dry-run`; live holds host lock from dispatch.

## Live verification

Code path + unit tests cover one iteration argv/flow per harness. A live
oneshot / propose on a host with coder weights is a follow-up when
MemAvailable and GGUF allow (see `docs/dogfood-daily.md`).
