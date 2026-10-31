# graph.yaml `options:`

Purpose: unplaced model option (catalog only; never placed or RAM-counted).

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:674` (stable; unplaced model option (catalog only; never placed or RAM-counted)).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-OPTIONS-001 | `role` | **req** | enum | one of `chat`, `coder`, `decision`, `diffusion`, `embed`, `guardian`, `pentest`, `reasoning`, `stt`, `tts`, `vision` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/start_graph.py` |
| CFG-GRAPH-OPTIONS-002 | `unverified` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-003 | `sources` | **req** | list | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-004 | `hf_repo` | opt | str | nullable | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-005 | `size_note` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-006 | `placement_note` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-007 | `candidate_hosts` | opt | strlist | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-008 | `gpu_candidate` | opt | bool | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-009 | `gpu_host` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-010 | `runtime_note` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-011 | `notes` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-OPTIONS-012 | `db` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |

<!-- END GENERATED: fields -->
