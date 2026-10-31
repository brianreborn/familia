# graph.yaml `swarms:`

Purpose: set of rooms.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:644` (experimental; set of rooms).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-SWARMS-001 | `experimental` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-SWARMS-002 | `rooms` | **req** | refs | ref → `rooms` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py` |

<!-- END GENERATED: fields -->
