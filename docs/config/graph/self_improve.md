# graph.yaml `self_improve:`

Purpose: Harness² optimizer setting over harness descriptors (off by default; pentest agents excluded).

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:657` (experimental; Harness² optimizer setting over harness descriptors (off by default; pentest agents excluded)).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-SELFIMPROVE-001 | `experimental` | **req** | bool | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/self_improve.py` |
| CFG-GRAPH-SELFIMPROVE-002 | `engine` | **req** | enum | one of `harness2` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/licenses.py`, `scripts/self_improve.py`, `scripts/terminal_rsi.py` |
| CFG-GRAPH-SELFIMPROVE-003 | `mode` | **req** | enum | one of `apply`, `off`, `propose` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/harness2_local.py`, `scripts/hermes_modes.py`, `scripts/licenses.py`, `scripts/self_improve.py` +1 |
| CFG-GRAPH-SELFIMPROVE-004 | `targets` | **req** | refs | ref → `harnesses` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/hermes_modes.py`, `scripts/self_improve.py` |
| CFG-GRAPH-SELFIMPROVE-005 | `k` | **req** | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/self_improve.py`, `scripts/terminal_rsi.py` |
| CFG-GRAPH-SELFIMPROVE-006 | `recursion` | **req** | enum | one of `parallel`, `sequential` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/self_improve.py` |
| CFG-GRAPH-SELFIMPROVE-007 | `tasks` | **req** | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/harness2_local.py`, `scripts/self_improve.py`, `scripts/terminal_rsi.py` |
| CFG-GRAPH-SELFIMPROVE-008 | `max_tasks` | opt | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/self_improve.py` |
| CFG-GRAPH-SELFIMPROVE-009 | `notes` | opt | str | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/licenses.py`, `scripts/self_improve.py` |

<!-- END GENERATED: fields -->
