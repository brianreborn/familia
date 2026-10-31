# Config-usage duplication audit

How the config files (docs/config/README.md matrix) are parsed, defaulted, validated and rendered in more than one place.
Purpose: pick one owner module per cluster and delete the copies. **Nothing is deleted or refactored in this PR** — the user approves deletions first.
Each cluster is pinned by a conformance test in `tests/test_config_consumers.py`; a divergence is a strict xfail citing the cluster.
LOC estimates are the duplicated bodies that would go away once callers use the owner (not the owner itself).

| # | Cluster | Owner (keep) | Duplicates (delete) | Reqs | ~LOC | Risk |
|---|---|---|---|---|---|---|
| DUP-01 | graph.yaml loader (open + YAML + `_path`) | **DONE** `familia_yaml.load` (raw: `familia_yaml.load`) | offline_improve.py:51-57; monitor.py:45-52; guardian_ready.py:45-49; modify_graph.py:49-52; model_db.py:662-665; scale_down.py:190; generate_graph.py:33-34; escalate.py:31; self_improve_attach.py:136; terminal_rsi.py:138; registry.py:223; host_measure.py:175; reconnect_selfheal.py (via oi); familia_agent_reach.py:43-48; skills.py:144-148 | CFG-FILE-007, CFG-GRAPH-* | 90 | low; overlay/`_path` behaviour must be preserved per caller |
| DUP-02 | graph path + `FAMILIA_GRAPH` resolution | one `config_paths.graph_path(environ,args)` | familia_agent_reach.py:39-40; skills.py:141; licenses.py:519; sec_assess.py:198-199; android_target.py:30; activate_guardian_weights.py:89-95; guardian_ready.py:37 (**ignores env**); model_db.py:664,843 (**ignores env**); modify_graph.py:43; generate_graph.py:27; offline_improve.py:330; monitor; scale_down.py:186; harness2.py:345; self_improve_attach.py:118; reconnect_selfheal.py:645; hermes_harness.py:814; escalate.py:20 | CFG-FILE-007, CFG-RULE | 60 | medium; env precedence currently inconsistent (see xfail) |
| DUP-03 | active/planned node filter (auto-route eligibility) | one `node_state.auto_nodes(graph,host)` | start_graph.py:122-137,147; validate_graph.py:108,126,233,446; ctx_vvram.py:51; graph_types.py:171,261; registry.py:128 | CFG-GRAPH-NODES-102, CFG-SPEC-PLAN-002 | 70 | medium; planned sub-states (routing-spec) must land in the owner |
| DUP-04 | llama-server launch argv / `--tools` builder | `validate_graph.server_args` (+ `merge_args`) | start_graph.py:209-240 re-reads argv; model_params.py arg parsing 120-162; hermes_harness launch bits | CFG-GRAPH-NODES-108, CFG-SPEC-TOOLS-001 | 120 | high; argv is the actual process launch — refactor behind the suite |
| DUP-05 | role / TYPE inference + alias→node resolution | `node_role` + `graph_types.lookup` | graph_types.py:337-352 (agent aliases); validate_graph.py:415; node_role.py:39-77; model_db role views; hermes_harness aliases | CFG-GRAPH-NODES-104, CFG-GRAPH-ALIASES-*, CFG-SPEC-ALIAS | 80 | medium |
| DUP-06 | host/port/bind + loopback checks | one `endpoints.node_url/loopback_ok` | start_graph.py:158-188; escalation.py:126; monitor probes; probe_links.py; graph_types.py:231-233 | CFG-SPEC-TOOLS-004, CFG-SPEC-GW-003 | 55 | low |
| DUP-07 | guardian/pentest role JSON load + dual-disable | one `pentest_policy.load_role` | guardian_ready.py:39-40; sec_assess.py:44-45,300-309; pentest-role.json/guardian-role.json readers | CFG-PENT-CUR-003, CFG-PENT-POL-* | 45 | medium; security seatbelt — keep behaviour identical |
| DUP-08 | secret stripping / `${VAR}` secret refs | `hermes_harness.strip_secrets` + `mcp_servers` | ad-hoc redaction in licenses/privacy lint; hosts_overlay privacy_lint overlaps | CFG-CRED-001..003 | 30 | low |
| DUP-09 | registry YAML loaders (hosts, hardware, model-params, builds) | `registry.py` loaders | registry.py:49,54; model_params/model_db re-open same files | CFG-FILE-002..005 | 40 | low |
| DUP-10 | REPO/ROOT discovery | `config_paths.ROOT` (partial) | 40 `ROOT=`/`REPO_ROOT=` defs across scripts/ | — | 35 | low; mechanical |

Total estimated deletable: **~625 LOC** across 10 clusters (owner modules excluded).

## Recommended sequence (after user approval)
1. DUP-10 then DUP-02 (path/root — mechanical, unblocks the rest).
2. DUP-01 (loader) — every consumer goes through the overlay-aware loader.
3. DUP-03, DUP-05, DUP-06 (resolution helpers).
4. DUP-07, DUP-08 (security-sensitive; land with the pentest-policy SPEC).
5. DUP-04 last (live launch argv; gate on the task-suite #119).

Each step: move the body to the owner, delete the copies, keep the conformance test green (flip its xfail to pass), update docs/config and requirement-ids.yaml in the same PR (CFG-RULE-001).


## Completed (this PR, swarm/routing/config-dedupe)
- **DUP-02** owner `scripts/config_paths.py` (`graph_path`, `default_graph`). Rerouted: guardian_ready, model_db (both previously ignored `$FAMILIA_GRAPH`), familia_agent_reach, skills, offline_improve, harness2, self_improve_attach, reconnect_selfheal, licenses, escalate. Conformance xfail flipped to pass. CFG-FILE-007.
- **DUP-01** graph loaders routed through `familia_yaml.load`: generate_graph, scale_down, self_improve_attach, terminal_rsi, offline_improve, monitor, model_db. Parity verified against yaml.safe_load on the real graph. CFG-FILE-007.
