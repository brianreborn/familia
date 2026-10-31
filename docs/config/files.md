# Non-graph config files

| ID | File | Purpose / schema | Writers | Readers | Invariants |
|---|---|---|---|---|---|
| CFG-FILE-001 | `registry/models/<org>--<repo>--<file>.json` | Model database, one per weight file (docs/model-database.md) | model_db.py:79,392; add_model.py | graph_types.py:562,672 (`models.db`), licenses.py:227, model_db.py:1081 | Every value cites its source; name+version, not hash-only |
| CFG-FILE-002 | `registry/model-params.yaml` | REQUIRED/RECOMMENDED sampling, chat-template decisions | hand edit (cited) | model_params.py:16,853; validate_graph.py --args | Each value quotes a card/config/GGUF line |
| CFG-FILE-003 | `registry/llama-builds/<build>.json` | Flag table per llama.cpp build | hand / bench tooling | llama_flags.py:6; model_db.py:1059; bench_guard.py:10 | Unknown build → flag support unverified (warning) |
| CFG-FILE-004 | `registry/hardware/*.yaml` | Shareable hardware profiles | registry.py:159 | registry.py:5 | No hostnames/IPs/users |
| CFG-FILE-005 | `registry/hosts.yaml` | Host → hardware-profile id | registry.py | registry.py:6; graph_types (hosts) | Profile ids only |
| CFG-FILE-006 | `registry/harness2-tasks/<set>.json` | Harness² task sets | hand | harness2_local.py:11; self_improve.py:72 | `self_improve.*.tasks` must name an existing set |
| CFG-FILE-007 | `generated/graph-<host>.yaml` | Per-host private type-named topology | generate_graph.py:145-161; scale_down.py:219 | activate_guardian_weights.py:193; node_role.py:7 | Same schema as graph.yaml (graph/*.md); comments not preserved |
| CFG-FILE-007a | `$FAMILIA_GRAPH` graph selection | Chosen graph path for all consumers (`config_paths.graph_path`): explicit flag > `$FAMILIA_GRAPH` (expanduser+abspath; empty = unset) > `<repo>/graph.yaml`. The hosts overlay lookup follows the **resolved graph's directory**, so `$FAMILIA_GRAPH` also moves the overlay for guardian_ready/model_db. `model_db link_graph` line-edits the resolved `$FAMILIA_GRAPH` in place (may be a user path). | operator/env | config_paths.py; hosts_overlay.resolve_overlay_path; model_db.link_graph | No secrets; a user-path graph is the operator's choice |
| CFG-FILE-008 | `scripts/guardian-role.json`, `scripts/pentest-role.json` | Guardian launch manifest (tools.allow, launch_test_only) | hand | with-fleet.sh; android_start.sh:24-27; guardian_ready.py:39-40; sec_assess.py:44-45 | Dual-disable: `tools.allow: []` here **and** in graph (CFG-PENT-CUR-003) |
| CFG-FILE-009 | gateway manifest (temp JSON written by start_graph) | alias → `{kind,url}` for graph-proxy | start_graph.py:301 | green-roomz graph-proxy.mjs | kind ∈ chat/embedding today; SPEC extension CFG-SPEC-GW-003 |
| CFG-FILE-010 | `~/.cache/familia/hermes-<agent>/config.yaml` | Generated hermes config | hermes_harness.py:284,547 | hermes-agent | See hermes-config.md; never hand-edit |
| CFG-FILE-011 | `config/mcp-servers.agent-reach.example.json` | Example MCP block for the bootstraps repo | hand; familia_agent_reach.py:339 prints merge hint | operator | Example only; no secrets |
| CFG-FILE-012 | `code-bootstraps-llama.cpp/config/models-manifest.json` (sibling repo) | Installer model manifest | add_model.py:522,1348; add-model.sh | licenses.py:181; installer | Owned by the bootstraps repo; familia only appends |
| CFG-FILE-013 | `docs/testing/suites/familia-core-v1.yaml` + `result-record.schema.json` | #119 task suite and record schema | hand (revision bump) | task_suite_lib.py; task_suite_runner.py:296 writes records | Suite revision changes invalidate older evidence |
| CFG-FILE-014 | `docs/perf/config-search-space.yaml` | Model-config search space | hand | docs/perf/config-search-plan.md | No host addresses |
| CFG-FILE-015 | `scripts/menu-items.txt`, `scripts/menu-internal.txt`, `scripts/cli-commands.txt` | Menu and CLI tables | hand | familia-menu.sh:34; familia_cli.py:21-22; windows/familia-menu.ps1:266 | tests/test_cli.py checks the generated man page |
| CFG-FILE-016 | `pins.txt` | Pinned upstream revisions | hand | installer scripts | — |
| CFG-FILE-017 | `skills/catalog.json` | Skill catalog | hand | skill loader | — |
| CFG-FILE-018 | `scripts/dogfood/queue-*.yaml` | Dogfood work queues | hand | dogfood scripts | — |
| CFG-FILE-019 | `.github/swarm-conductor.json`, `.github/workflows/*.yml`, `.ci/warnings-baseline.txt`, `pytest.ini` | CI/swarm config | hand | GitHub Actions; pytest | CI must run `scripts/config_docs.py --check` (CFG-RULE-002) |
| CFG-FILE-020 | Untracked overlays (hosts overlay, `~/.hermes/config.yaml`, env) | Private addresses, logins, secrets | operator | hosts_overlay.py; android_target.py; hermes_harness.py | Never committed (credentials.md) |
