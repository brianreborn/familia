# graph.yaml `system_agents:`

Purpose: phone assistant (Bixby/Gemini) via Shizuku; cloud calls need consent; never for pentests.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:688` (experimental; phone assistant (Bixby/Gemini) via Shizuku; cloud calls need consent; never for pentests).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-SYSTEMAGENTS-001 | `kind` | **req** | enum | one of `system-agent` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/monitor/probe.py`, `scripts/monitor.py`, `scripts/system_agents.py` |
| CFG-GRAPH-SYSTEMAGENTS-002 | `provider` | **req** | enum | one of `bixby`, `gemini` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/system_agents.py` |
| CFG-GRAPH-SYSTEMAGENTS-003 | `backend` | **req** | enum | one of `app`, `nano` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/system_agents.py` |
| CFG-GRAPH-SYSTEMAGENTS-004 | `host` | **req** | ref | ref → `hosts` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/monitor.py`, `scripts/system_agents.py` |
| CFG-GRAPH-SYSTEMAGENTS-005 | `transport` | **req** | enum | one of `shizuku` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/monitor.py` |
| CFG-GRAPH-SYSTEMAGENTS-006 | `cloud` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/system_agents.py` |
| CFG-GRAPH-SYSTEMAGENTS-007 | `consent` | **req** | enum | one of `ask` | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-SYSTEMAGENTS-008 | `status` | **req** | enum | one of `active`, `off`, `planned` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/monitor/probe.py`, `scripts/monitor.py`, `scripts/system_agents.py` |
| CFG-GRAPH-SYSTEMAGENTS-009 | `experimental` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py` |
| CFG-GRAPH-SYSTEMAGENTS-010 | `agents` | opt | refs | ref → `agents` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/system_agents.py` |
| CFG-GRAPH-SYSTEMAGENTS-011 | `notes` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/system_agents.py` |

<!-- END GENERATED: fields -->
