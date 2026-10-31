# graph.yaml `stores:`

Purpose: persistent state.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:645` (experimental; persistent state).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-STORES-001 | `experimental` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/self_improve.py` |
| CFG-GRAPH-STORES-002 | `kind` | **req** | enum | one of `fs`, `git`, `sqlite` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py`, `scripts/self_improve.py` |
| CFG-GRAPH-STORES-003 | `host` | **req** | ref | ref → `hosts` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py` |
| CFG-GRAPH-STORES-004 | `path` | **req** | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_env_probe_cache/familia_env_probe_cache.py`, `scripts/self_improve.py` |

<!-- END GENERATED: fields -->
