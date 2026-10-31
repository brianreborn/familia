# graph.yaml `gateways:`

Purpose: an alias router (green-roomz graph-proxy) on one host.

## Semantics and invariants
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-GRAPH-GATEWAYS-101 | One gateway per host is launched by start_graph when that host has manifest aliases | IMPLEMENTED | start_graph.py:136-180, 450 |
| CFG-GRAPH-GATEWAYS-102 | The graph-proxy accepts backend kinds chat and embedding only | IMPLEMENTED | start_graph.py:169; green-roomz src/graph-proxy.mjs:27 |
| CFG-GRAPH-GATEWAYS-103 | The gateway accepts guardian/pentest/decision backends for explicit slash requests; auto-routing ignores them | SPEC | routing-spec.md CFG-SPEC-GW-001 |
| CFG-GRAPH-GATEWAYS-104 | Every host with an active node has a router (one router per host keyed by TYPE) | SPEC | routing-spec.md CFG-SPEC-GW-002 |

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:596` (stable; router exposing aliases).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-GATEWAYS-001 | `kind` | **req** | enum | one of `green-roomz` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py`, `scripts/start_graph.py` |
| CFG-GRAPH-GATEWAYS-002 | `host` | **req** | ref | ref → `hosts` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py`, `scripts/start_graph.py` |
| CFG-GRAPH-GATEWAYS-003 | `port` | **req** | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/node_role.py`, `scripts/start_graph.py` |

<!-- END GENERATED: fields -->
