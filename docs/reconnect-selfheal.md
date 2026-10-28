# Reconnect + self-heal (no models) — issue #149

**Intent:** every host must try to get back onto the network the way it originally
joined (SSH nexus proxy, LAN, tunnels). A small **model-free** probe decides
whether the host looks reachable / locally healthy enough to rejoin, then
exponentially retries with bounded, seatbelted self-repair.

Composes with [offline-improve.md](./offline-improve.md) / PR #148
(`scripts/offline_improve.py`): reuses `fleet_reachable`, `peer_hosts`, and
`backoff_seconds`. Offline improve may still run optional `llama-bench` when
disconnected; **this** layer never loads or benches models.

## CLI

```sh
# One probe (JSON); exit 0 = healthy|online_ish, 2 = local_ok_fleet_down, 1 = offline
python3 scripts/reconnect_selfheal.py --probe-only

# Probe once; optional seatbelted repair (dry-run by default)
python3 scripts/reconnect_selfheal.py --once --repair
python3 scripts/reconnect_selfheal.py --once --repair --no-dry-run   # still seatbelted

# Loop until online_ish (or --stop-at healthy)
python3 scripts/reconnect_selfheal.py --loop --repair

# Documented helpers
python3 scripts/reconnect_selfheal.py --show-backoff
python3 scripts/reconnect_selfheal.py --list-actions

sh scripts/reconnect_selfheal.sh --probe-only --host angel
```

State: `~/.local/state/familia/reconnect-selfheal/<host>/`
(`latest.json`, `probe-*.json`, `history.jsonl`). Override with
`FAMILIA_RECONNECT_DIR`.

## Probe states (settle-once per cycle)

| State | Meaning |
|-------|---------|
| `offline` | Local net probe failed (no default route / DNS) and fleet peers down |
| `local_ok_fleet_down` | DNS or default route OK; SSH BatchMode to peers fails |
| `online_ish` | At least one fleet peer up **or** a local `/health` is 200 while still recovering |
| `healthy` | Fleet peer(s) up **and** all configured local health URLs are 200 (or none configured) |

Local checks (fail soft, short timeout, **no LLM**):

1. Default route (`ip route show default` / `route -n get default`)
2. DNS resolve of `FAMILIA_RECONNECT_DNS` (default `1.1.1.1`)
3. Optional loopback `GET /health` from `FAMILIA_RECONNECT_HEALTH_URLS` and/or
   `graph.yaml` nodes on this host
4. Fleet: same `ssh -o BatchMode=yes PEER 'echo familia-fleet-ok'` as offline_improve

## Documented backoff schedule

Formula: `min(cap, base * 2**(fails-1))` with defaults **base=30s**, **cap=900s**.

| fails | sleep (s) |
|------:|----------:|
| 1 | 30 |
| 2 | 60 |
| 3 | 120 |
| 4 | 240 |
| 5 | 480 |
| 6+ | 900 (cap) |

Optional jitter: ±`FAMILIA_RECONNECT_JITTER` (default `0.1`) but **never above cap**.
Env: `FAMILIA_RECONNECT_BASE`, `FAMILIA_RECONNECT_CAP`.

## Self-repair actions (seatbelted)

Enum (`--list-actions`):

| Action | Default | Seatbelt |
|--------|---------|----------|
| `check_screen` | always runs | read-only `screen -ls` |
| `restart_screen_attached` | dry-run | **Refuses** unless `DETACH_MODE` / `FAMILIA_DETACH_MODE` is `screen-attached`. Live start also requires `FAMILIA_RECONNECT_ALLOW_START=1`. Never cold-Popen llama; never kill live servers outside this path. |
| `reapply_hook` | dry-run / noop | Runs `FAMILIA_RECONNECT_HOOK` (script-only nexus/SSH/tunnel rejoin). If unset → structured noop stub. |
| `git_fetch_tip` | skipped | Only when `FAMILIA_RECONNECT_PULL=1` **and** git tree is clean. Never surprise-pull on dirty trees. |

`--repair` enables the sequence; repair stays **dry-run** unless `--no-dry-run`.
Agents must not set `DETACH_MODE` to anything other than `screen-attached` for
service restarts (see LESSONS-LEARNED / start.sh).

## Nexus / SSH rejoin (host classes)

Conceptually smokeable on **angel** (desktop FreeBSD/Linux SSH peer) or a
**phone** (Termux SSH):

1. `--probe-only --host angel --peers miryam,box` — expect `local_ok_fleet_down`
   or better when LAN is up.
2. Set `FAMILIA_RECONNECT_HOOK='ssh -o BatchMode=yes miryam echo familia-fleet-ok'`
   (or a real tunnel/nexus script) and `--once --repair` to exercise the hook path.
3. Unit tests mock SSH / DNS / health — no live angel required on the box.

Existing fleet join surfaces: `with-fleet.sh`, `scripts/nexus/nexus.py`,
`offline_improve.py --check-only`. This module does not replace them; it probes
and optionally re-invokes a hook.

## Race notes

- **Settle-once:** one probe result drives the whole repair/backoff iteration
  (no mid-cycle TOCTOU re-classify).
- **No fail-open past health/tools:** restart path never bypasses the
  screen-attached seatbelt.
- Probe path has **zero** model / llama-bench calls.

## Wire-ups

| Surface | Status |
|---------|--------|
| `scripts/reconnect_selfheal.py` / `.sh` | **implemented** (#149) |
| `scripts/offline_improve.py` | shared backoff + fleet SSH (PR #148) |
| Continuity gum | not owned here |
| Live host restarts from automation | refused without screen-attached + `FAMILIA_RECONNECT_ALLOW_START=1` |

See also: [offline-improve.md](./offline-improve.md), [monitoring.md](./monitoring.md),
[vvram-ssd/ANGEL-OPERATOR.md](./vvram-ssd/ANGEL-OPERATOR.md).
