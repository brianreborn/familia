# graph.yaml `nodes:`

Purpose: one model instance (weights × runtime × host). The node TYPE (`role`, else `models.<m>.role`) carries capability.

## Semantics and invariants
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-GRAPH-NODES-101 | `status: planned` nodes are schema-checked only: host-measured, runtime-on-host, arch and port-clash checks are skipped | IMPLEMENTED | graph_types.py:171-238 |
| CFG-GRAPH-NODES-102 | Only `status: active` local nodes are started by start_graph | IMPLEMENTED | start_graph.py:119-123 |
| CFG-GRAPH-NODES-103 | `ctx % parallel == 0`; per-slot ctx ≤ `models.trained_ctx` (no inflation) | IMPLEMENTED | graph_types.py:205-209 |
| CFG-GRAPH-NODES-104 | `role` may differ from the model role only as: chat/general view of coder, general of chat, guardian/defender of pentest | IMPLEMENTED | graph_types.py:179-193 |
| CFG-GRAPH-NODES-105 | Model arch ∈ runtime `supported_archs` (upgrade the runtime, never drop the model) | IMPLEMENTED | graph_types.py:194-202 |
| CFG-GRAPH-NODES-106 | No two non-planned nodes share host+port | IMPLEMENTED | graph_types.py:213-216 |
| CFG-GRAPH-NODES-107 | `server_tools`: `all` or a non-empty list ⊆ SERVER_TOOL_NAMES; loopback bind only | IMPLEMENTED | graph_types.py:218-233 |
| CFG-GRAPH-NODES-108 | Launch argv comes only from `validate_graph.py --args` (REQUIRED/RECOMMENDED model params; `--tools` only if `server_tools` is set) | IMPLEMENTED | validate_graph.py:399-440 |
| CFG-GRAPH-NODES-109 | `escalates_to` / `escalation` per docs/escalation.md (no self, no cycles, known nodes, mode off/suggest/auto) | IMPLEMENTED | escalation.py:36-61 |
| CFG-GRAPH-NODES-110 | Planned sub-states and slash reachability (see [routing-spec.md](../routing-spec.md) CFG-SPEC-PLAN-*) | SPEC | — |
| CFG-GRAPH-NODES-111 | Explicit `--tools` per TYPE on every llama-server launch (CFG-SPEC-TOOLS-*) | SPEC | validate_graph.py:418-423 emits only when set |

Writers: `modify_graph.py` (assign-model / split-node), `generate_graph.py`, `scale_down.py:219`, `activate_guardian_weights.py:265` (planned→active only by operator).

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:571` (stable; model instance on host+runtime).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-NODES-001 | `model` | **req** | ref | ref → `models` | IMPLEMENTED | `scripts/activate_guardian_weights.py`, `scripts/add_model.py`, `scripts/ctx_vvram.py`, `scripts/dogfood/dispatch.py`, `scripts/dogfood/loop.sh`, `scripts/escalation.py` +16 |
| CFG-GRAPH-NODES-002 | `host` | **req** | ref | ref → `hosts` | IMPLEMENTED | `scripts/activate_guardian_weights.py`, `scripts/ctx_vvram.py`, `scripts/escalation.py`, `scripts/escalation_proxy.py`, `scripts/generate_graph.py`, `scripts/graph_types.py` +12 |
| CFG-GRAPH-NODES-003 | `runtime` | **req** | ref | ref → `runtimes` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/model_db.py`, `scripts/registry.py`, `scripts/scale_down.py`, `scripts/start_graph.py` +1 |
| CFG-GRAPH-NODES-004 | `ctx` | **req** | int | min 1 | IMPLEMENTED | `scripts/add_model.py`, `scripts/ctx_vvram.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/hermes_modes.py`, `scripts/model_db.py` +2 |
| CFG-GRAPH-NODES-005 | `parallel` | **req** | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/hermes_modes.py`, `scripts/model_db.py`, `scripts/monitor.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-006 | `kv_type` | **req** | enum | one of `bf16`, `f16`, `f32`, `q4_0`, `q8_0` | IMPLEMENTED | `scripts/ctx_vvram.py`, `scripts/graph_types.py`, `scripts/monitor.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-007 | `flash_attn` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-008 | `offload` | **req** | any | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/registry.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-009 | `bind` | **req** | str | — | IMPLEMENTED | `scripts/dogfood/dispatch.py`, `scripts/escalation_proxy.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/reconnect_selfheal.py`, `scripts/self_improve.py` +2 |
| CFG-GRAPH-NODES-010 | `port` | **req** | int | min 1 | IMPLEMENTED | `scripts/dogfood/dispatch.py`, `scripts/escalation_proxy.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/modify_graph.py`, `scripts/monitor.py` +6 |
| CFG-GRAPH-NODES-011 | `cache_ram_mib` | **req** | int | min 0 | IMPLEMENTED | `scripts/ctx_vvram.py`, `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-012 | `status` | **req** | enum | one of `active`, `planned` | IMPLEMENTED | `scripts/activate_guardian_weights.py`, `scripts/ctx_vvram.py`, `scripts/dogfood/dispatch.py`, `scripts/escalation_proxy.py`, `scripts/generate_graph.py`, `scripts/graph_types.py` +14 |
| CFG-GRAPH-NODES-013 | `embeddings` | opt | bool | — | IMPLEMENTED | `scripts/add_model.py`, `scripts/graph_types.py`, `scripts/model_db.py`, `scripts/start_graph.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-014 | `threads` | opt | int | min 1 | IMPLEMENTED | `scripts/dogfood/dispatch.py`, `scripts/graph_types.py`, `scripts/monitor.py`, `scripts/registry.py`, `scripts/scale_down.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-015 | `scale_down` | opt | any | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/scale_down.py` |
| CFG-GRAPH-NODES-016 | `load_mode` | opt | enum | one of `auto`, `mmap`, `none` | IMPLEMENTED | `scripts/ctx_vvram.py`, `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-017 | `slot_save` | opt | bool | — | IMPLEMENTED | `scripts/ctx_vvram.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-018 | `spill_path` | opt | str | — | IMPLEMENTED | `scripts/ctx_vvram.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-019 | `swap_budget_mib` | opt | int | min 0 | IMPLEMENTED | `scripts/ctx_vvram.py`, `scripts/graph_types.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-020 | `selection` | opt | enum | one of `default`, `fallback` | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-NODES-021 | `note` | opt | str | — | IMPLEMENTED | `scripts/add_model.py`, `scripts/dogfood/dispatch.py`, `scripts/graph_types.py`, `scripts/guardian_ready.py` |
| CFG-GRAPH-NODES-022 | `escalates_to` | opt | list | — | IMPLEMENTED | `scripts/escalate.py`, `scripts/escalation.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/hermes_modes.py`, `scripts/node_role.py` |
| CFG-GRAPH-NODES-023 | `escalation` | opt | any | — | IMPLEMENTED | `scripts/escalation.py`, `scripts/graph_types.py`, `scripts/hermes_modes.py` |
| CFG-GRAPH-NODES-024 | `card_set` | opt | str | — | IMPLEMENTED | `scripts/add_model.py`, `scripts/graph_types.py`, `scripts/model_db.py` |
| CFG-GRAPH-NODES-025 | `sampling` | opt | map | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/model_db.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-026 | `override_reasons` | opt | map | — | IMPLEMENTED | `scripts/add_model.py`, `scripts/graph_types.py`, `scripts/model_db.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-027 | `server_tools` | opt | any | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-NODES-028 | `role` | opt | enum | one of `chat`, `coder`, `decision`, `diffusion`, `embed`, `general`, `guardian`, `pentest`, `reasoning`, `vision` | IMPLEMENTED | `scripts/add_model.py`, `scripts/escalation.py`, `scripts/escalation_proxy.py`, `scripts/graph_types.py`, `scripts/guardian_ready.py`, `scripts/hermes_harness.py` +7 |

<!-- END GENERATED: fields -->
