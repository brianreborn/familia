# graph.yaml `speculative:`

Purpose: edge draft->target (same vocab) or model-free n-gram lookup decoding.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:616` (experimental; edge draft->target (same vocab) or model-free n-gram lookup decoding).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-SPECULATIVE-001 | `experimental` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-SPECULATIVE-002 | `status` | **req** | enum | one of `active`, `experimental`, `planned` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-003 | `mode` | **req** | enum | one of `draft`, `ngram` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-004 | `target` | **req** | ref | ref → `nodes` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py`, `scripts/perf/spec_bench.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-005 | `spec_type` | opt | enum | one of `draft-dflash`, `draft-dspark`, `draft-eagle3`, `draft-mtp`, `draft-simple`, `ngram-cache`, `ngram-map-k`, `ngram-map-k4v`, `ngram-mod`, `ngram-simple` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-006 | `draft` | opt | ref | ref → `models` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/perf/spec_bench.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-007 | `draft_max` | opt | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-008 | `draft_min` | opt | int | min 0 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-009 | `p_min` | opt | num | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-010 | `draft_ctx` | opt | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-011 | `draft_kv_type` | opt | enum | one of `bf16`, `f16`, `f32`, `q4_0`, `q8_0` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-012 | `draft_ngl` | opt | int | min 0 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-SPECULATIVE-013 | `notes` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/perf/spec_bench.py` |

<!-- END GENERATED: fields -->
