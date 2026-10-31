# graph.yaml `fleets:`

Purpose: green-agentz agent group.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:611` (stable; green-agentz agent group).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-FLEETS-001 | `repo` | **req** | str | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-FLEETS-002 | `agents` | **req** | refs | ref → `agents` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py` |

<!-- END GENERATED: fields -->
