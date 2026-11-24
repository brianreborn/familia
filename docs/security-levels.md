# Security node levels

Turn the security nodes (guardian, pentest seats, and any other fail-closed node) on or off by
**named level**, without editing `graph.yaml`. The level is a local overlay merged when the graph
is loaded. `graph.yaml` is never rewritten.

```sh
familia security status              # what is on, what is off, and why
familia security guardian            # guardian/defender monitoring only
familia security pentest             # guardian + pentest seats (asks you to type "pentest")
familia security off                 # every security node off
familia start --security-level=off   # one run only; nothing is saved
```

`familia-security …` (repo root) is the canonical command; `familia security …` runs the same script
(`scripts/security_levels.py`). Menu: *Agents (hermes)* → `security.status`, `security.list`,
`security.level`. The gum home shows the level under **Agents → status**.

## Levels

Defined in one data file, [`config/security-levels.yaml`](../config/security-levels.yaml), not in code.

| level | sets on | effect |
|---|---|---|
| `off` | none | every security node and pentest seat is `planned` |
| `guardian` | guardian | guardian/defender nodes (`fleet-guardian`, `freebsd-guardian`) `active`; pentest seats `planned` |
| `pentest` | guardian, pentest | plus `pentests.fleet` and `pentests.freebsd-guardian` `active` (still operator-start only) |
| `full` | guardian, pentest, other | plus any other fail-closed node (role or model role guardian/pentest/defender) |

Sets match graph entries by **role**, not by name, so private type-named graphs
(`generated/graph-HOST.yaml`, node key `guardian`) work the same. A new security node is picked up
by its role; add explicit keys under `sets.<set>.nodes` if it uses another role.

| set | members | rules |
|---|---|---|
| `guardian` | nodes with role `guardian` or `defender` | — |
| `pentest` | every `pentests.*` seat, nodes with role `pentest` | needs `guardian`; **typed confirmation** |
| `other` | any remaining fail-closed node | `full` only |

## Toggles

```sh
familia security enable pentest      # one set on top of the current level (asks for confirmation)
familia security disable guardian    # one set off; disable wins over enable
familia security clear               # remove the override: graph.yaml as declared
familia security list                # levels, sets and their members in this graph
familia security status --json
```

Every command is idempotent: setting the level you already have prints `no change` and writes nothing.

## Where the level comes from

Precedence: `familia start --security-level=LEVEL` > `FAMILIA_SECURITY_LEVEL` > override file >
`graph.yaml` as declared (no override = no change at all).

The override file reuses the [hosts overlay](hosts-overlay.md) (#104/#97) lookup:

1. `$FAMILIA_SECURITY_OVERRIDE`
2. `$XDG_CONFIG_HOME/familia/security.local.yaml` (default `~/.config/familia/`; Windows `%LOCALAPPDATA%\familia\`)
3. `security.local.yaml` next to `graph.yaml` (gitignored)

```yaml
# security.local.yaml (written by familia security; never commit)
level: "guardian"
enable: [pentest]      # optional extra sets
disable: []            # optional sets forced off
confirmed: [pentest]   # recorded typed confirmation; dropped when the set goes off
```

The overlay is applied by `familia start` (`scripts/start_graph.py`), `familia validate`
(`scripts/validate_graph.py`) and `with-fleet.sh` (role resolution and `--operator-start`).
A malformed override file or an unknown level is refused with a clear error; nothing guesses.

## Safety: the same at every level

- A level only changes `status` (`active`/`planned`). Roles, aliases, `escalates_to`, `tool_route`,
  `tools.allow`, `launch_test_only` and `requires_operator_confirm` are never touched, and the
  validator still runs after the overlay.
- `familia start` never launches a guardian/pentest/defender node at any level; their gateway aliases
  (`guardian`, `pentest`, `defender`) are listed as omitted, never routed, and they are never an
  escalation target (see [planned-to-active](planned-to-active.md)).
- The pentest set needs a **typed confirmation on a terminal** (type `pentest`). There is no `--yes`
  and no environment bypass: `FAMILIA_SECURITY_LEVEL=pentest` or `--security-level=pentest` only turns
  the seats on if that confirmation is already recorded in the override file. Lowering the level drops
  the confirmation, so raising it again asks again.
- A pentest seat is only on when its node is on.
- Starting a seat is still the operator path, unchanged:
  `FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh --role guardian --operator-start`. It refuses when the
  level keeps the seat off.
- Turning a node on checks its model file on this machine. A missing GGUF is a clear error naming the
  file and the fetch step (`scripts/activate_guardian_weights.py`, [guardian-weights](guardian-weights.md));
  `--no-files` sets the level anyway (the validator still reports it). Nodes on other hosts are not checked here.
- `off` is also the way to validate a graph whose guardian weights are not fetched yet.

## With the planned-to-active flow (#693)

#693 makes the guardian nodes and pentest seats `active` in `graph.yaml`. With no override that is
what you get. `familia security guardian` keeps the guardian nodes and parks the pentest seats;
`familia security off` parks all of them locally while the weights download, without touching the
tracked file.

Tests: `tests/test_security_levels.py`.
