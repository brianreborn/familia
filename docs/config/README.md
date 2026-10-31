# familia configuration: requirements and reference

This directory is the **contract** between every program that reads or writes familia config, today and later (graph editors, routers, harnesses, installers).
Code and tests cite the requirement IDs (`CFG-…-NNN`). The IDs are stable and never renumbered. Registry: [requirement-ids.yaml](requirement-ids.yaml), managed by `scripts/config_docs.py`.

## Index
| Doc | Covers |
|---|---|
| [graph/*.md](graph/) | `graph.yaml`: one doc per top-level section (hosts, runtimes, models, nodes, aliases, agents, gateways, pentests, …). The field tables are generated from `scripts/graph_types.py`; the semantics/invariants are hand-written |
| [routing-spec.md](routing-spec.md) | Planned-state semantics, gateway role exposure, alias-as-list (#150), `--tools` per TYPE, MCP/toolsets/prompt_profile, escalation |
| [pentest-policy.md](pentest-policy.md) + [spec/pentest-policy.schema.yaml](spec/pentest-policy.schema.yaml) | Full pentest mode ladder up to autonomous-in-isolated-lab, the lab verification and the audit log |
| [hermes-config.md](hermes-config.md) | Generated hermes-agent config |
| [credentials.md](credentials.md) | Secret handling convention |
| [files.md](files.md) | Every non-graph config file: writers and readers |

## Producer / consumer matrix (graph.yaml)
| Program | Reads | Writes |
|---|---|---|
| graph_types.py / validate_graph.py | all sections (schema, `--args` argv) | — |
| start_graph.py | nodes, aliases, gateways, hosts | gateway manifest (start_graph.py:301) |
| hermes_harness.py / hermes_modes.py | agents, aliases, nodes, hosts | hermes config (hermes_harness.py:284,547) |
| escalation.py | nodes.escalates_to/escalation | consent state |
| modify_graph.py | all | graph.yaml (modify_graph.py:242,252) |
| generate_graph.py | all | generated/graph-HOST.yaml (:145-161) |
| scale_down.py | nodes, models, hosts | graph copy (:219) |
| activate_guardian_weights.py | nodes, models, pentests | graph.yaml planned→active (:265) |
| guardian_ready.py, sec_assess.py | pentests, nodes, role JSONs | reports |
| licenses.py, model_db.py, model_params.py | models, runtimes | registry/models (model_db) |
| with-fleet.sh, start.sh, android_*.sh, watchdog_android.sh, familia-menu.sh | graph via validate_graph | — |
| task_suite_*.py | suite YAML, graph/node identity | evidence records |
Per-field consumers appear in each graph/*.md table (static scan; 37 scripts load the graph).

## Status totals
Run `python3 scripts/config_docs.py --check`. Counts by status are kept in requirement-ids.yaml.

## Rule
CFG-RULE-001: Any change to a config file, its schema or its consumers updates docs/config and requirement-ids.yaml **in the same PR**. CFG-RULE-002: `tests/test_config_docs.py` (offline) fails when a schema field has no documented requirement ID.
