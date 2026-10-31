# graph.yaml `transports:`

Purpose: host-to-host link.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:553` (stable; host-to-host link).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-TRANSPORTS-001 | `kind` | **req** | enum | one of `bittorrent`, `local`, `nfs`, `rsync`, `ssh`, `zfs` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/nexus/nexus.py`, `scripts/transport_graph.py`, `scripts/validate_graph.py` |
| CFG-GRAPH-TRANSPORTS-002 | `from` | **req** | ref | ref → `hosts` | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-TRANSPORTS-003 | `to` | **req** | ref | ref → `hosts` | IMPLEMENTED | `scripts/graph_types.py` |

<!-- END GENERATED: fields -->
