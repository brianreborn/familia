# graph.yaml `aliases:`

Purpose: route name → node, exposed by a gateway. Today it is exactly one node per alias.

## Semantics and invariants
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-GRAPH-ALIASES-101 | If the gateway host ≠ node host, a non-local transport between them must exist | IMPLEMENTED | graph_types.py:306-311 |
| CFG-GRAPH-ALIASES-102 | start_graph puts only aliases to **active, local, loopback** chat/coder/embed nodes in the graph-proxy manifest. Others are omitted with a warning | IMPLEMENTED (conflicts with CFG-SPEC-PLAN-005) | start_graph.py:142-178 |
| CFG-GRAPH-ALIASES-103 | An alias to a planned node is valid, kept in the manifest, slash-reachable, never silently dropped | SPEC | routing-spec.md CFG-SPEC-PLAN-005 |
| CFG-GRAPH-ALIASES-104 | `node` may be a list of nodes (same-role multi-engine, #150) with `policy` | SPEC | routing-spec.md CFG-SPEC-ALIAS-001 |

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:626` (stable; route name -> exactly one node).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-ALIASES-001 | `node` | **req** | ref | ref → `nodes` | IMPLEMENTED | `scripts/escalation_proxy.py`, `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/hermes_harness.py`, `scripts/hermes_modes.py`, `scripts/monitor.py` +5 |
| CFG-GRAPH-ALIASES-002 | `gateway` | **req** | ref | ref → `gateways` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py`, `scripts/start_graph.py` |

<!-- END GENERATED: fields -->
