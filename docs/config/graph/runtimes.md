# graph.yaml `runtimes:`

Purpose: a pinned inference engine build installed on hosts.

## Semantics and invariants
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-GRAPH-RUNTIMES-101 | llama-server `commit` is a git sha or `pkg:<name>=<ver>` (never a branch) | IMPLEMENTED | graph_types.py:150-155 |
| CFG-GRAPH-RUNTIMES-102 | `backends` ⊆ cpu + GPU_BACKENDS and must include cpu; `spec_types` ⊆ SPEC_TYPES | IMPLEMENTED | graph_types.py:156-165 |
| CFG-GRAPH-RUNTIMES-103 | Only `kind: llama-server` has server args (validate_graph --args refuses others) | IMPLEMENTED | validate_graph.py:399-403 |
| CFG-GRAPH-RUNTIMES-104 | Flags are checked against registry/llama-builds/<build>.json; an unsupported flag is a blocker | IMPLEMENTED | scripts/llama_flags.py, model_db.runtime_build |

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:555` (stable; inference engine build).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-RUNTIMES-001 | `kind` | **req** | enum | one of `drex-dlm`, `llama-server`, `reference`, `sm11-legacy` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/licenses.py`, `scripts/model_db.py`, `scripts/start_graph.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-RUNTIMES-002 | `build` | **req** | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/model_db.py` |
| CFG-GRAPH-RUNTIMES-003 | `commit` | **req** | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-RUNTIMES-004 | `hosts` | **req** | refs | ref → `hosts` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/registry.py`, `scripts/start_graph.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-RUNTIMES-005 | `supported_archs` | **req** | list | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-RUNTIMES-006 | `backends` | **req** | list | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-RUNTIMES-007 | `spec_types` | **req** | strlist | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-RUNTIMES-008 | `bin` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/serve.sh`, `scripts/start_graph.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-RUNTIMES-009 | `quants` | opt | strlist | — | IMPLEMENTED | `scripts/graph_types.py` |

<!-- END GENERATED: fields -->
