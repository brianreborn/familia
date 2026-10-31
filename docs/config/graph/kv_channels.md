# graph.yaml `kv_channels:`

Purpose: C2C stage 1 edge: llama-server slot save/restore file shipped between same-model nodes (#22).

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:665` (experimental; C2C stage 1 edge: llama-server slot save/restore file shipped between same-model nodes (#22)).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-KVCHANNELS-001 | `experimental` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-KVCHANNELS-002 | `status` | **req** | enum | one of `active`, `experimental`, `planned` | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-KVCHANNELS-003 | `from` | **req** | ref | ref → `nodes` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py` |
| CFG-GRAPH-KVCHANNELS-004 | `to` | **req** | ref | ref → `nodes` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py` |
| CFG-GRAPH-KVCHANNELS-005 | `via` | **req** | enum | one of `bt`, `local`, `nexus` | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-KVCHANNELS-006 | `transport` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-KVCHANNELS-007 | `slot` | opt | int | min 0 | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-KVCHANNELS-008 | `notes` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py` |

<!-- END GENERATED: fields -->
