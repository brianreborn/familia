# graph.yaml `hosts:`

Purpose: one physical box. A host is placement only. A node's TYPE carries capability, never the host name.

## Semantics and invariants
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-GRAPH-HOSTS-101 | `measured: true` requires the HOST_FACTS fields; `kind` must not be `unknown`; `reported` is forbidden | IMPLEMENTED | graph_types.py:84-90 |
| CFG-GRAPH-HOSTS-102 | `measured: false` must not carry measured facts (threads, ram_mib, vram_mib, reserve_ram_mib); `reported` needs a `source` | IMPLEMENTED | graph_types.py:91-97 |
| CFG-GRAPH-HOSTS-103 | `reserve_ram_mib < ram_mib` | IMPLEMENTED | graph_types.py:89 |
| CFG-GRAPH-HOSTS-104 | `os: windows` requires a `windows:` block and vice versa (keys WINDOWS_KEYS; startup rules) | IMPLEMENTED | graph_types.py:99-119 |
| CFG-GRAPH-HOSTS-105 | Tracked graph.yaml never carries real `addr`/`user`/`port`. They live in the untracked overlay (hosts-overlay.md) | IMPLEMENTED | scripts/hosts_overlay.py:1-20 |
| CFG-GRAPH-HOSTS-106 | Unmeasured hosts are excluded from placement: an active node on an unmeasured host is an error | IMPLEMENTED | graph_types.py:172 |
| CFG-GRAPH-HOSTS-107 | `kind` selects the archetype default shape (roles, reserve, transports) used by generate_graph | IMPLEMENTED | scripts/box_archetypes.py |

Writers: `scripts/host_measure.py:205` (installers call it), `scripts/modify_graph.py:242`, `scripts/generate_graph.py:145`.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:563` (stable; physical/dedicated form-factor box (see box_archetypes.HOST_KINDS); not virtualization).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-HOSTS-001 | `kind` | **req** | enum | one of `1U`, `2U`, `3U`, `appliance`, `console`, `desktop`, `drone`, `laptop`, `notebook`, `phone`, `tablet`, `unknown`, `watch` | IMPLEMENTED | `scripts/android_target.py`, `scripts/escalation.py`, `scripts/generate_graph.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/host_measure.py` +9 |
| CFG-GRAPH-HOSTS-002 | `measured` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/host_measure.py`, `scripts/registry.py`, `scripts/sec_assess.py` |
| CFG-GRAPH-HOSTS-003 | `os` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/host_measure.py`, `scripts/monitor.py`, `scripts/registry.py`, `scripts/sec_assess.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-HOSTS-004 | `cpu` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/host_measure.py`, `scripts/monitor.py`, `scripts/registry.py` |
| CFG-GRAPH-HOSTS-005 | `threads` | opt | int | min 1 | IMPLEMENTED | `scripts/dogfood/dispatch.py`, `scripts/graph_types.py`, `scripts/host_measure.py`, `scripts/monitor.py`, `scripts/registry.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-HOSTS-006 | `ram_mib` | opt | int | min 1 | IMPLEMENTED | `scripts/ctx_vvram.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/host_measure.py`, `scripts/registry.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-HOSTS-007 | `gpus` | **req** | gpus | nullable | IMPLEMENTED | `scripts/graph_types.py`, `scripts/host_measure.py`, `scripts/monitor.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-HOSTS-008 | `reserve_ram_mib` | opt | int | min 0 | IMPLEMENTED | `scripts/box_archetypes.py`, `scripts/ctx_vvram.py`, `scripts/dogfood/dispatch.py`, `scripts/graph_types.py`, `scripts/host_measure.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-HOSTS-009 | `notes` | opt | str | — | IMPLEMENTED | `scripts/box_archetypes.py`, `scripts/graph_types.py`, `scripts/system_agents.py` |
| CFG-GRAPH-HOSTS-010 | `reported` | opt | any | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-HOSTS-011 | `windows` | opt | any | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/host_measure.py`, `scripts/monitor.py` |
| CFG-GRAPH-HOSTS-012 | `local_names` | opt | strlist | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/host_measure.py`, `scripts/start_graph.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-HOSTS-013 | `addr` | opt | str | — | IMPLEMENTED | `scripts/android_target.py`, `scripts/escalation_proxy.py`, `scripts/graph_types.py`, `scripts/hosts_overlay.py`, `scripts/monitor.py`, `scripts/transport_graph.py` |
| CFG-GRAPH-HOSTS-014 | `user` | opt | str | — | IMPLEMENTED | `scripts/android_target.py`, `scripts/escalation.py`, `scripts/escalation_proxy.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/hosts_overlay.py` +2 |
| CFG-GRAPH-HOSTS-015 | `port` | opt | int | min 1 | IMPLEMENTED | `scripts/android_target.py`, `scripts/dogfood/dispatch.py`, `scripts/escalation_proxy.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/hosts_overlay.py` +6 |

<!-- END GENERATED: fields -->
