# Security node levels

Turn the security nodes (guardian, pentest seats, and any other fail-closed node) on or off by
**named level**, without editing `graph.yaml`. The level is a local overlay merged when the graph
is loaded. `graph.yaml` is never rewritten.

Each node also has a risk tier (`low`, `medium`, `high`). Low is the default.
Raising it is a separate command (`familia security tier`) and is never a side
effect of a preset. See "Risk tiers" below. Integrity labels (#684, #699) are
a third axis and are not set here.

```sh
familia security status              # what is on, what is off, and why
familia security guardian            # guardian/defender monitoring only
familia security pentest             # guardian + pentest seats (asks you to type "pentest")
familia security off                 # every security node off
familia start --security-level=off   # one run only; nothing is saved
```

`familia-security` (repo root) is the canonical command; `familia security` runs the same script
(`scripts/security_levels.py`). Menu: *Agents (hermes)*: `security.status`, `security.list`,
`security.level`. The gum home shows the level under **Agents: status**.

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
| `guardian` | nodes with role `guardian` or `defender` | (none) |
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
# confirmed: is ignored. A pentest set stays off until a signed grant exists.
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

## On main, before #693

This command set is the #700 design, retargeted at current `main`. It does not
require #693. With no override, `graph.yaml` is used as declared: the guardian
nodes and pentest seats on `main` are `planned`. `familia security guardian`
marks the guardian nodes `active` in the local overlay only. `familia security off`
parks every security node locally while weights are still downloading.
[#693](https://github.com/brianreborn/familia/pull/693) would make those seats
`active` in the tracked file; the overlay still parks them without editing it.
`familia start` does not launch a fail-closed node either way.

## Three different "levels"

Do not treat these as one ladder.

| Axis | Names | What it means | Where |
|---|---|---|---|
| Preset | `off`, `guardian`, `pentest`, `full` | Which security nodes are `active` in the local overlay | `familia security <level>` (#700) |
| Risk tier | `low`, `medium`, `high` | How much one node is allowed to do. Default `low` | `familia security tier` |
| Integrity | provenance `untrusted` / `screened` / `validated` / `trusted`, or a traditional `low` / `medium` / `high` profile | How much an artifact or task is trusted. A producer cannot promote its own output | #684, #699. Not set by this command |

A traditional integrity profile reuses the words low, medium, and high. Those
words are not risk tiers. `familia security low` is an unknown preset on
purpose, so it cannot be read as either an integrity write or a fleet-wide
risk change. Risk tiers are per node, under `tier`.

Integrity promotion (#684) needs a validator that is not the producing task.
Risk escalation uses the same idea: the node process does not hold the factor
that raises its own tier.

## Risk tiers

Defined in `config/security-levels.yaml` next to the presets, checked by
`config/security-levels.schema.json`. Every node type familia already names
(swarm worker, model server, coding agent, the graph roles, host kinds,
gateway, system agent, speech) has `low`, `medium`, and `high`.

| Tier | Arming | Meaning |
|---|---|---|
| low | none | Default. Smallest capability set. A missing record is low, and `show` does not create a file. |
| medium | explicit-arm | Adds capabilities. Needs a terminal, the admin key, and a signed grant file that is consumed. |
| high | strongest-confirm | Largest set. Same admin context. The grant is signed and expires. |

Changing a tier does not edit `graph.yaml`, does not write `security.local.yaml`,
does not set `FAMILIA_FLEET_ARM`, and does not open a listener. A preset does
not raise a tier, and a tier does not flip a preset. Both are deliberate.

### Pentest-policy map

For a `guardian` node (aliases `pentest` and `defender`) the tier permits modes
from [pentest-policy.md](config/pentest-policy.md). It does not write
`policy.mode`. Only `planned` is built today (CFG-PENT-POL-006: a mode change
is a graph edit plus evidence, and nothing at runtime raises the mode).

| Risk tier | Modes the tier permits |
|---|---|
| low | `off`, `planned` |
| medium | `slash-confirm` |
| high | `tools-confirm` |
| not granted | `autonomous-lab` |

Other node types have `policy: none`. Their tiers do not unlock the pentest ladder.

### Escalate

Raising a tier needs an operator `--actor` that is not the node id, a higher
`--to`, and an out-of-band factor:

- to `medium`: `--confirm-file`, or an admin token
- to `high`, including a jump from `low`: `--admin-token-file` plus the admin key

A raise needs a terminal and the admin key. A missing `FAMILIA_NODE_ID` is not
permission. The grant file is two lines (v2 grant plus hmac-sha256), mode 0600
or 0400, owned by the operator, not a symlink, not under a group or world
writable directory, and outside the repo, the tier state directory,
`FAMILIA_NODE_HOME`, and `FAMILIA_NODE_WRITABLE`. It names the node, the tier,
a nonce, and an expiry, and it is deleted when used. Mint it from an operator
shell:

```
umask 077
python3 scripts/security_levels.py tier mint-token \
  --host miryam --node fleet-guardian --type guardian \
  --from low --to medium --actor brian --reason "arm slash-confirm" \
  --admin-key-file "$HOME/.config/familia/tier-admin.key" \
  --out "$HOME/.config/familia/tier-grant"
python3 scripts/security_levels.py tier escalate \
  --host miryam --node fleet-guardian --type guardian \
  --to medium --actor brian --reason "arm slash-confirm" \
  --confirm-file "$HOME/.config/familia/tier-grant" \
  --admin-key-file "$HOME/.config/familia/tier-admin.key"
```

`grant-line` only prints an unsigned line. It does not authorize a raise. High tier:

```
umask 077
python3 scripts/security_levels.py tier mint-token \
  --host miryam --node fleet-guardian --type guardian \
  --from medium --to high --actor brian --reason "tools-confirm" \
  --admin-key-file "$HOME/.config/familia/tier-admin.key" \
  --out "$XDG_RUNTIME_DIR/familia-tier-token"
python3 scripts/security_levels.py tier escalate \
  --host miryam --node fleet-guardian --type guardian \
  --to high --actor brian --reason "tools-confirm" \
  --admin-token-file "$XDG_RUNTIME_DIR/familia-tier-token" \
  --admin-key-file "$HOME/.config/familia/tier-admin.key"
```

The key file is one line, at least 16 bytes, mode 0600 or 0400, outside the
repo and outside node roots. It is never stored in this repository. A reused
nonce is refused. `mint-token` is refused when the process is a node.

### De-escalate

Lowering does not need a terminal or a grant file. Re-signing a recorded tier
needs the admin key. Without a valid signature, show fails closed to low.

```
python3 scripts/security_levels.py tier de-escalate \
  --host miryam --node fleet-guardian --to low \
  --actor fleet-guardian --reason "back to planned"
```

### A node cannot self-escalate

`familia start`, hermes, and the swarm run loop set `FAMILIA_TIER_CALLER=node`
and `FAMILIA_NODE_ID`, and they remove `FAMILIA_FLEET_ADMIN_KEY_FILE` from the
child environment. A raise also needs a positive admin context: a terminal and
a readable admin key. Unsetting the node marker does not grant that.
`--actor` equal to the node id is refused. `off`, `disable`, and `clear` stay
available.

The tier file is HMAC-SHA256 with the admin key. A bad signature, a symlink, or
an audit log whose tip or inode does not match that signature is treated as
low. The audit log is append-only, opened with O_NOFOLLOW, and each line stores
the hash of the previous line. A grant carries `exp`. A nonce is accepted only
for the audit file the signature is bound to.

The pentest preset does not trust `confirmed:` in security.local.yaml. Turning
that set on needs a terminal and the nonce the prompt prints, and the grant is
signed. The override is opened with O_NOFOLLOW, must be mode 0600 or 0400, and
is written atomically at mode 0600. An environment variable still cannot
confirm the pentest set.

## Audit log

Every preset change and every tier change appends one JSON line to
`$FAMILIA_SECURITY_AUDIT` or `~/.local/state/familia/security-audit.log`.
The writer opens the file with `O_APPEND` and `O_NOFOLLOW` and never rewrites
earlier lines. Each line stores `prev`, the SHA-256 of the previous line.
`familia security tier audit-check` refuses a broken chain.

Fields: `ts` (UTC), `host`, `node`, `type`, `old_tier`, `new_tier`, `actor`,
`reason`, `factor` (`confirm-file`, `admin-token`, `local`, or `preset`),
`nonce`, `prev`, `kind` (`tier` or `preset`).

Recorded tiers live in `~/.local/state/familia/node-tiers.json` (mode 0600),
not in `graph.yaml` and not in `security.local.yaml`.

## Menu

Agents (hermes): `security.status`, `security.list`, `security.level`,
`security.tier-show`, `security.tier-escalate`, `security.tier-deescalate`.
`familia security tier types`, `tier schema`, `tier grant-line`, and
`tier mint-token` are the same script.

Tests: `tests/test_security_levels.py`, `tests/test_security_tiers.py`.
