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
