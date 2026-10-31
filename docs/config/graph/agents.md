# graph.yaml `agents:`

Purpose: an agent process (hermes-agent) and its model aliases, skills, plugins and MCP servers. Rendered to `~/.cache/familia/hermes-<agent>/config.yaml` (see [../hermes-config.md](../hermes-config.md)).

## Semantics and invariants
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-GRAPH-AGENTS-101 | `aliases` has exactly `main` and `auxiliary`, one alias each (no lists) | IMPLEMENTED | graph_types.py:338-347 |
| CFG-GRAPH-AGENTS-102 | per-slot ctx of each alias ≥ `min_ctx`; `context_length` == main per-slot ctx | IMPLEMENTED | graph_types.py:348-354 |
| CFG-GRAPH-AGENTS-103 | `mcp.<srv>` keys ⊆ {command,url,args,env_from,headers_from,tools,enabled,notes}; exactly one of command/url; secrets only as env var **names** | IMPLEMENTED (b3e282d) | graph_types.py:318-333 |
| CFG-GRAPH-AGENTS-104 | `prompt_profile` auto ⇒ lean on phones or hosts with ram_mib < 8192; lean keeps only terminal,file,todo,clarify,skills **plus graph-declared `mcp-<srv>`** | IMPLEMENTED | hermes_harness.py prompt_profile / lean_toolsets |
| CFG-GRAPH-AGENTS-105 | `plugins` links named dirs from ~/.hermes/plugins (opt-in) | IMPLEMENTED | hermes_harness.py link_plugins |
| CFG-GRAPH-AGENTS-106 | main/auxiliary map to node TYPEs and route through the host router | SPEC | routing-spec.md CFG-SPEC-AGENT-001 |
| CFG-GRAPH-AGENTS-107 | Explicit `toolsets:` selection per agent/TYPE (no silent RAM-only trim; warn when auto→lean) | SPEC | routing-spec.md CFG-SPEC-AGENT-002 |

## Field reference

<!-- BEGIN GENERATED: fields (scripts/config_docs.py --write) -->

Schema: `scripts/graph_types.py:606` (stable; agent process).
Required fields have no defaults (validator: missing required → error). Consumers = static scan of scripts/ and top-level *.sh.

| ID | Field | Req | Type | Allowed / ref | Status | Consumers (static scan) |
|---|---|---|---|---|---|---|
| CFG-GRAPH-AGENTS-001 | `kind` | **req** | enum | one of `hermes-agent` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/hermes_harness.py`, `scripts/licenses.py`, `scripts/monitor/probe.py`, `scripts/monitor.py` +4 |
| CFG-GRAPH-AGENTS-002 | `host` | **req** | ref | ref → `hosts` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/hermes_harness.py`, `scripts/hermes_modes.py`, `scripts/licenses.py`, `scripts/monitor.py` +3 |
| CFG-GRAPH-AGENTS-003 | `prompt_profile` | opt | enum | one of `auto`, `full`, `lean` | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_harness.py` |
| CFG-GRAPH-AGENTS-004 | `min_ctx` | **req** | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_modes.py` |
| CFG-GRAPH-AGENTS-005 | `context_length` | **req** | int | min 1 | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_harness.py`, `scripts/hermes_modes.py` |
| CFG-GRAPH-AGENTS-006 | `aliases` | **req** | map | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/hermes_harness.py`, `scripts/hermes_modes.py`, `scripts/node_role.py`, `scripts/self_improve.py` |
| CFG-GRAPH-AGENTS-007 | `skills` | opt | strlist | — | IMPLEMENTED | `scripts/familia_agent_reach.py`, `scripts/graph_types.py`, `scripts/harness2.py`, `scripts/harness2_local.py`, `scripts/hermes_harness.py`, `scripts/hermes_modes.py` +3 |
| CFG-GRAPH-AGENTS-008 | `plugins` | opt | strlist | — | IMPLEMENTED | `scripts/graph_types.py`, `scripts/hermes_harness.py` |
| CFG-GRAPH-AGENTS-009 | `mcp` | opt | map | — | IMPLEMENTED | `scripts/familia_agent_reach.py`, `scripts/graph_types.py`, `scripts/hermes_harness.py` |

<!-- END GENERATED: fields -->
