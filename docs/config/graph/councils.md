# graph.yaml `councils:`

Purpose: multi-agent decision (quorum N-of-M or ordered cascade).

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:627` (experimental; multi-agent decision (quorum N-of-M or ordered cascade)).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-COUNCILS-001 | `experimental` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-COUNCILS-002 | `mode` | **req** | enum | one of `cascade`, `quorum` | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-COUNCILS-003 | `agents` | **req** | refs | ref → `agents` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py` |
| CFG-GRAPH-COUNCILS-004 | `quorum` | opt | int | — | IMPLEMENTED | `scripts/graph_types.py` |

<!-- END GENERATED: fields -->
