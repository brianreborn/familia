# Guardian / defender nodes

Guardian (also called defender) is a **first-class node flavor** beside coder and
chat: an owned-fleet advisory model role. It is not a special forbidden product.

## Seatbelts, not barricades

Default seatbelts (on until the operator widens them):

1. `tools.allow: []` in `graph.yaml` `pentests.*` and `scripts/guardian-role.json`
2. `launch_test_only: true` so automation stays validate → would-start → stop

Empty `scope.allow` is additional default-deny (keeps home appliances off the
target list). The owned-fleet allowlist prefers **angel**, **galaxy1**,
**gabriel**, **galaxy2** (legacy host keys may still appear in inventory).

Widening seatbelts is an explicit graph edit + `requires_operator_confirm: true`
(see `scripts/graph_types.py` `check_pentest`). Do not remove either tools
disable for CI or smoke tests ([REQUIREMENTS.md](../REQUIREMENTS.md)).

`scripts/pentest-role.json` is the legacy filename for the same dual-disable
stub as `scripts/guardian-role.json`.

## Ready-check (Boundary lane)

Offline, fail-closed readiness — **never** flips `planned` → `active`, **never**
fetches weights, **no network**:

```sh
python3 scripts/guardian_ready.py
python3 scripts/guardian_ready.py --graph graph.yaml --json
```

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | Seatbelts OK **and** GGUF present with sha256 matching the graph |
| 2 | Seatbelts OK, but weights MISSING / UNMEASURED / MISMATCH |
| 1 | Seatbelt or schema failure (e.g. non-empty `tools.allow`) |

Who does what:

| Lane | Owns |
|------|------|
| **Boundary** (this doc / `guardian_ready.py`) | Dual-disable seatbelts, ready-check, docs/tests that keep CI tools disabled |
| **Hermes Wiring / operator** | Fetch Dolphin3-Cyber-8B Q2_K (or successor), measure sha256 into `graph.yaml`, then flip node + `pentests.*` to `active` |
| **Operator** | One-time seatbelt widen via graph edit + confirm — never strip CI dual-disable |

Seatbelts are not barricades: the operator may widen them deliberately. The
ready-check only reports; it does not activate.

## Launch

```sh
# Safe smoke (no model process required for PASS):
sh with-fleet.sh --role guardian --launch-test

# Private per-host graph (type-named nodes; includes guardian when declared):
python3 scripts/generate_graph.py angel
python3 scripts/generate_graph.py miryam   # Ubuntu laptop host key in graph.yaml

# Model-only start after weights + status active + measured sha:
FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh --role guardian --operator-start
```

Aliases: `--role fleet`, `--role pentest`, `--role defender` → same entry.

Menus: `agents.guardian-launch-test`, `agents.guardian-start` (legacy
`agents.pentest-*` ids still work).

## Graph hooks

- Model catalog role may still say `pentest`; public node type is `guardian`
- Fleet node key: `miryam-pentest` (transitional); private topology renames to `guardian`
- Planned: `angel-guardian` → private key `guardian` on angel
- Section name `pentests:` remains the schema type; UX name is guardian/defender

Weights / placement details: [pentest-models.md](pentest-models.md).
