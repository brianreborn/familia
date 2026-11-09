# hermes-agent pin

familia does not clone or install [hermes-agent](https://github.com/NousResearch/hermes-agent);
you install it (snap, FreeBSD `pkg install hermes-agent`, the upstream `install.sh`, or a venv).
familia does say **which release it targets**, per release channel, and checks the interpreter.

## Where the ref comes from

One hook, `scripts/hermes_pin.py` (`resolve_ref()`), is the only place a Hermes ref is chosen:

1. If `scripts/channel.py` (release channels) is in the tree, it validates
   `FAMILIA_CHANNEL=bleeding|stable` (default `bleeding`) and `FAMILIA_STABLE_DAYS=N`, and resolves
   the `hermes-agent` source: bleeding = newest non-prerelease, stable = most stable release in
   the last N days. If the network fails, the channel's pin below is used (`fallback: true`).
2. Otherwise, or with `--offline`, the channel-keyed pin in `config/hermes-agent.pins.json` is used.

An invalid channel or day count is an error (exit 2), never a silent default.

| Channel | Ref | Commit | Notes |
|---|---|---|---|
| bleeding (default) | `v0.22.6` | `f0d94882e89a` | equal to upstream `main` on 2026-11-02 |
| stable | `v0.22.5` | `bf0203a794a0` | 30-day longest soak on 2026-11-02 |

Python floor: **3.14** (upstream declares its dependencies only for python >= 3.14).

```sh
python3 scripts/hermes_pin.py resolve                       # ref for the effective channel
FAMILIA_CHANNEL=stable python3 scripts/hermes_pin.py resolve --json
python3 scripts/hermes_pin.py check                         # installed `hermes --version` vs the pin
```

To install the targeted ref with upstream's installer: `install.sh --commit <commit>`
(or `--channel stable|main`, upstream's own channels).

## At launch (`scripts/hermes.sh`)

- The full `hermes` CLI is used. In pip/uv/install.sh layouts `hermes-agent` is upstream's legacy
  single-query runner (`agent.legacy_cli`, no `-z`/`-t`/`desktop`/`webapp`); when it is what PATH
  finds and a `hermes` sits beside it, that `hermes` is launched instead. An explicit `HERMES_BIN`
  still wins, with a warning.
- A warning when `HERMES_PY` is older than the python floor.
- `FAMILIA_HERMES_PIN_CHECK=1` also compares the installed version with the channel's pin
  (offline, no network at launch); `=strict` refuses a mismatch.
  `FAMILIA_HERMES_TOOLCHAIN_CHECK=0` skips both checks.

## Checking a new upstream release

Install the tag into a venv (`uv sync --frozen --no-dev` in a checkout of the tag), then:

```sh
FAMILIA_HERMES_UPSTREAM_PY=/path/to/venv/bin/python python3 -m pytest tests/test_hermes_upstream_compat.py
```

That loads the rendered HERMES_HOME with that hermes (config schema incl. `mcp_servers` and
`approvals`, toolsets, MCP `${VAR}` interpolation, aux routing, skills, child-process symbols).
Then update the channel's entry in `config/hermes-agent.pins.json`.

Auxiliary tasks not routed to the local node: `vision`, `voice_chat`, `moa_reference`,
`moa_aggregator` (they need a vision/voice-capable node).
