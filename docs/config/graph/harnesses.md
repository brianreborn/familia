# graph.yaml `harnesses:`

Purpose: target harness descriptor: prompt/guardrails/memory/skills paths + local endpoint.

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:653` (stable; target harness descriptor: prompt/guardrails/memory/skills paths + local endpoint).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-HARNESSES-001 | `kind` | **req** | enum | one of `files` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/licenses.py`, `scripts/node_role.py`, `scripts/self_improve.py`, `scripts/terminal_rsi.py` |
| CFG-GRAPH-HARNESSES-002 | `root` | **req** | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/harness2_local.py`, `scripts/self_improve.py` |
| CFG-GRAPH-HARNESSES-003 | `prompt` | **req** | str | — | IMPLEMENTED | `scripts/dogfood/dispatch.py`, `scripts/graph_types.py`, `scripts/harness2_local.py`, `scripts/self_improve.py`, `scripts/terminal_rsi.py` |
| CFG-GRAPH-HARNESSES-004 | `guardrails` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/self_improve.py` |
| CFG-GRAPH-HARNESSES-005 | `memory` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/self_improve.py` |
| CFG-GRAPH-HARNESSES-006 | `skills` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/harness2_local.py`, `scripts/hermes_modes.py`, `scripts/licenses.py`, `scripts/self_improve.py` |
| CFG-GRAPH-HARNESSES-007 | `node` | **req** | ref | ref → `nodes` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/harness2_local.py`, `scripts/hermes_modes.py`, `scripts/licenses.py`, `scripts/node_role.py` +1 |
| CFG-GRAPH-HARNESSES-008 | `agent` | opt | ref | ref → `agents` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/hermes_modes.py`, `scripts/node_role.py`, `scripts/self_improve.py`, `scripts/self_improve_attach.py` +1 |
| CFG-GRAPH-HARNESSES-009 | `notes` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/self_improve.py` |

<!-- END GENERATED: fields -->
