# graph.yaml `agencies:`

Purpose: GitHub-style issue workflow (not the retired green-agency repo).

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:618` (stable; GitHub-style issue workflow (not the retired green-agency repo)).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-AGENCIES-001 | `repo` | **req** | str | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-AGENCIES-002 | `labels` | **req** | list | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-AGENCIES-003 | `assignments` | **req** | map | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py` |

<!-- END GENERATED: fields -->
