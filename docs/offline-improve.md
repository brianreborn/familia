# Offline improve loop — stay useful when disconnected

**Intent (Brian, 2026-10-27):** when a host/peer/gateway drops off the fleet it
should **not** idle. It should enter a local performance-improvement loop,
persist results, periodically retry reconnect, and when back online report what
improved offline then resume normal duty.

## On-host command

```sh
# Are fleet peers reachable from this machine?
python3 scripts/offline_improve.py --check-only

# One bounded improve cycle if offline (or force with --offline)
python3 scripts/offline_improve.py --once
python3 scripts/offline_improve.py --offline --once

# Improve → sleep/backoff → reconnect check → repeat until a peer answers
python3 scripts/offline_improve.py --loop

# Wrapper
sh scripts/offline_improve.sh --loop --host angel
```

State lands under `~/.local/state/familia/offline-improve/<host>/`
(`latest.json`, `improve-*.json`, `history.jsonl`). Override with
`FAMILIA_OFFLINE_IMPROVE_DIR`.

## What one cycle does

1. **Host RAM memcpy probe** (stdlib; same idea as `scripts/probe_links.py`).
2. **Bounded `llama-bench`** on a *small* local GGUF when available
   (`LFM2.5-1.2B` / SmolLM2-class — **not** Nanbeige 33B). Thread grid is
   `{1, ncpu/2, ncpu}`. Skip with `--no-bench` or when no bench/GGUF exists.
3. Persist JSON + append `history.jsonl`.

Reconnect uses `ssh -o BatchMode=yes PEER 'echo familia-fleet-ok'` against other
`graph.yaml` hosts (or `--peers`). Backoff starts at 30s and caps at 15m
(`FAMILIA_OFFLINE_IMPROVE_BASE` / `_CAP`).

## Wire-ups

| Surface | Status |
|---------|--------|
| `scripts/offline_improve.py` / `.sh` | **implemented** |
| `familia-monitor --on-death '…'` | can launch `--once` on process death (operator choice) |
| Continuity gum / `setup_goals` | **hook only** — see comment in `scripts/menu-internal.txt`; Continuity owns gum rows |
| Researcher weekday fleet nudge | routine prompt (parent); not this script |

Example death hook:

```sh
./familia-monitor --watch-deaths --on-death \
  'python3 scripts/offline_improve.py --once --host "$FAMILIA_HOST"'
```

## Angel / private topology

After `generate_graph.py angel`, nodes are type-named (`coder` / `chat`). Offline
improve does not start Nanbeige; it only benches a small GGUF so a disconnected
angel still gathers useful thread/RAM numbers until miryam/box answer SSH again.

See also: [reconnect-selfheal.md](./reconnect-selfheal.md) (issue #149 — online-ish
probe + exponential reconnect + seatbelted self-repair; **no models** on the probe
path; reuses this module's fleet SSH + backoff),
[vvram-ssd/ANGEL-OPERATOR.md](./vvram-ssd/ANGEL-OPERATOR.md),
[monitoring.md](./monitoring.md), [perf/config-search-plan.md](./perf/config-search-plan.md).
