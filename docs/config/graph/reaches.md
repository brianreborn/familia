# graph.yaml `reaches:`

Purpose: agent-reach tool bundle.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:625` (experimental; agent-reach tool bundle).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-REACHES-001 | `experimental` | **req** | bool | — | IMPLEMENTED | `scripts/familia_agent_reach.py`, `scripts/graph_types.py` |
| CFG-GRAPH-REACHES-002 | `repo` | **req** | str | — | IMPLEMENTED | `scripts/familia_agent_reach.py`, `scripts/graph_types.py` |
| CFG-GRAPH-REACHES-003 | `agents` | **req** | refs | ref → `agents` | IMPLEMENTED | `scripts/familia_agent_reach.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/node_role.py` |

<!-- END GENERATED: fields -->
