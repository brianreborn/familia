# graph.yaml `meshes:`

Purpose: multi-member transport (ssh nexus / bittorrent swarm).

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:557` (stable; multi-member transport (ssh nexus / bittorrent swarm)).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-MESHES-001 | `type` | **req** | enum | one of `bittorrent`, `ssh` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hosts_overlay.py`, `scripts/transport_graph.py` |
| CFG-GRAPH-MESHES-002 | `members` | **req** | refs | ref → `hosts` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/transport_graph.py` |
| CFG-GRAPH-MESHES-003 | `hub` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/transport_graph.py` |
| CFG-GRAPH-MESHES-004 | `root` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/transport_graph.py` |
| CFG-GRAPH-MESHES-005 | `identity` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/transport_graph.py` |
| CFG-GRAPH-MESHES-006 | `host_key_policy` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/transport_graph.py` |
| CFG-GRAPH-MESHES-007 | `tracker` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hosts_overlay.py`, `scripts/transport_graph.py` |
| CFG-GRAPH-MESHES-008 | `bind` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hosts_overlay.py`, `scripts/transport_graph.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-MESHES-009 | `port` | opt | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hosts_overlay.py`, `scripts/transport_graph.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-MESHES-010 | `private` | opt | bool | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/transport_graph.py` |
| CFG-GRAPH-MESHES-011 | `client` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/transport_graph.py`, `scripts/validate_graph.py` |

<!-- END GENERATED: fields -->
