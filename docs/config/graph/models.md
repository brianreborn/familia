# graph.yaml `models:`

Purpose: one weights file plus identity. Labels use name + version, never a bare hash.

## Semantics and invariants
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-GRAPH-MODELS-101 | `db` names registry/models/<db>.json. A placed model without a DB entry fails `--args` | IMPLEMENTED | validate_graph.py:427-430 |
| CFG-GRAPH-MODELS-102 | `sha256` is a sha or `unmeasured`. Planned nodes may reference unmeasured weights | IMPLEMENTED | graph_types.py check_field sha; guardian_ready.check_weight |
| CFG-GRAPH-MODELS-103 | `role` is the catalog TYPE. Node `role` may present a compatible view (CFG-GRAPH-NODES-104) | IMPLEMENTED | graph_types.py:179-193 |
| CFG-GRAPH-MODELS-104 | Never skip a model for license reasons; licenses are gated by consent records | IMPLEMENTED | scripts/licenses.py, license_acceptance.py |

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:565` (stable; weights file).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-MODELS-001 | `gguf` | **req** | str | — | IMPLEMENTED | `scripts/activate_guardian_weights.py`, `scripts/add-model.sh`, `scripts/add_model.py`, `scripts/bench_guard.py`, `scripts/ctx_vvram.py`, `scripts/graph_types.py` +14 |
| CFG-GRAPH-MODELS-002 | `sha256` | **req** | sha | — | IMPLEMENTED | `scripts/activate_guardian_weights.py`, `scripts/add_model.py`, `scripts/familia_auth.py`, `scripts/graph_types.py`, `scripts/guardian_ready.py`, `scripts/hf_fetch.py` +7 |
| CFG-GRAPH-MODELS-003 | `arch` | **req** | str | — | IMPLEMENTED | `scripts/add_model.py`, `scripts/ctx_vvram.py`, `scripts/graph_types.py`, `scripts/model_db.py`, `scripts/scale_down.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-MODELS-004 | `trained_ctx` | **req** | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/model_db.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-MODELS-005 | `role` | **req** | enum | one of `chat`, `coder`, `decision`, `diffusion`, `embed`, `guardian`, `pentest`, `reasoning`, `vision` | IMPLEMENTED | `scripts/add_model.py`, `scripts/graph_types.py`, `scripts/guardian_ready.py`, `scripts/hermes_modes.py`, `scripts/launch_matrix.py`, `scripts/model_db.py` +7 |
| CFG-GRAPH-MODELS-006 | `derived_from` | opt | any | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/scale_down.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-MODELS-007 | `db` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/model_db.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-MODELS-008 | `notes` | opt | str | — | IMPLEMENTED | `scripts/add_model.py`, `scripts/bench_guard.py`, `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/model_db.py`, `scripts/offline_secbench.py` +2 |
| CFG-GRAPH-MODELS-009 | `quant` | opt | enum | one of `littlebit` | IMPLEMENTED | `scripts/add_model.py`, `scripts/graph_types.py`, `scripts/model_db.py`, `scripts/model_params.py`, `scripts/registry.py`, `scripts/scale_down.py` +2 |

<!-- END GENERATED: fields -->
