# graph.yaml `rooms:`

Purpose: shared conversation space.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:642` (experimental; shared conversation space).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-ROOMS-001 | `experimental` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-ROOMS-002 | `gateway` | **req** | ref | ref → `gateways` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py` |
| CFG-GRAPH-ROOMS-003 | `agents` | **req** | refs | ref → `agents` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py` |

<!-- END GENERATED: fields -->
