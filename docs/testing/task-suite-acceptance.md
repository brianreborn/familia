# Task-suite acceptance gate (#119)

Unit tests, schema validation, and a successful server load are **necessary but not sufficient** for substantial features or radically new model configurations. This document is the durable gate. Overview also lives in [REQUIREMENTS.md](../../REQUIREMENTS.md) and the short pointer in [TESTING.md](../../TESTING.md).

## When the gate applies

A configuration must stay `planned` / experimental (not `active`, and not `selection: default`) until it passes the fixed suite for its intended role and is compared to a baseline on the **same** tasks, seed, and platform class.

Treat any of these as a **radical change** (see `radical_change_triggers` in the suite YAML):

- new model family or architecture
- serving runtime or backend
- quantization
- tokenizer, chat template, or system prompt
- context length beyond the model card
- materially unusual sampling or tool configuration
- multi-engine same-role topology ([#150](https://github.com/brianreborn/familia/issues/150))

Substantial features need an end-to-end run on the real integrated path with representative inputs (not only mocks). Define success criteria **before** the run.

**Never** exercise live attack tools or network probes here. Pentest coverage remains launch-test-only.

**Never** skip a model for license reasons when designing or running acceptance.

## Fixed suite

Canonical suite: [`suites/familia-core-v1.yaml`](suites/familia-core-v1.yaml)

- Roles: chat, coder, general, decision, reasoning, embed
- Routing baselines: `always-light`, `always-heavy`, `random`
- Harness modes: plain llama.cpp, hermes single, hermes `--graph`, Harness² (optional)
- **#150 cases (planned now, even if schema lands later):** same-role multi-engine instances in competing, tandem, specialized, and escalate-across-engines modes (e.g. llama coder + other-engine coder on one host)
- Platforms: Ubuntu, Windows, FreeBSD, Samsung Android/Termux **A57 class** (two current A57 phones). Do not write Note9-only assumptions.

Result record schema: [`suites/result-record.schema.json`](suites/result-record.schema.json)

Each record must include: per-task outcomes, aggregate, model **name + version** (not hash-only), runtime name + commit, graph/prompt/template labels, suite id + revision, seed, platform class, harness, baseline id, gate decision, failures/limitations. Optional `host_key` is a graph key only — **no IPs, usernames, ports, or keys**.

## Tools

```sh
# Plan only (CI-safe, no model calls)
python3 scripts/task_suite_runner.py --dry-run --role coder --platform ubuntu

# Record against OpenAI-compatible endpoints (env only; never written into the JSON)
export FAMILIA_ENDPOINT="$YOUR_LOCAL_OPENAI_COMPAT_BASE"   # e.g. loopback llama-server /v1; never commit real endpoints
export FAMILIA_LIGHT_URL=...   # optional routing
export FAMILIA_HEAVY_URL=...
# #150 engines: FAMILIA_ENGINE_CODER_LLAMA_URL=... FAMILIA_ENGINE_CODER_OTHER_URL=...
python3 scripts/task_suite_runner.py --record --role coder --platform ubuntu \
  --model-name 'Qwen3.5-2B' --model-version '…' --quant Q4_K_M \
  --runtime-name llama-server --runtime-commit "$(git rev-parse --short HEAD)" \
  --status-before planned --radical-trigger quantization \
  --baseline candidate --harness plain-llamacpp

# Promote gate: refuse active/default without passing evidence
python3 scripts/task_suite_promote.py check --node-id coder --role coder \
  --model-name 'Qwen3.5-2B' --radical-trigger quantization
python3 scripts/task_suite_promote.py check-record path/to/evidence.json
```

Evidence directory: `FAMILIA_TASK_SUITE_EVIDENCE_DIR`, or `$XDG_STATE_HOME/familia/task-suite-evidence` (Windows: `%LOCALAPPDATA%\familia\task-suite-evidence`).

Exit codes: runner `--record` returns `1` when `gate.passed` is false; promote `check` returns `1` when promotion must be refused.

## Baseline comparison

1. Run the suite under `always-light`, `always-heavy`, and `random` (fixed seed) on the same platform class.
2. Run the candidate (router / multi-engine policy / new config) with the same seed and task subset for its role.
3. Aggregate gate (suite `aggregate_gate`): minimum pass rate; max regression vs baseline pass rate; escalation precision/recall when gold routes exist.

## Enforcement

- **Hard refuse:** `scripts/task_suite_promote.py check` must be run (or equivalent library call) before flipping a node to `active` or marking `selection: default` after a radical change. Missing or failed evidence → refuse.
- Offline unit tests: `tests/test_task_suite_gate.py` (no live models).
- Existing active nodes on older revisions are grandfathered until their next radical change; the promote CLI still refuses a new promotion without evidence.

## Routing acceptance (#199)

Router/alias changes must also pass `tests/test_router_199.py` (offline fake-server routing per node type). Known no-op cases are strict xfails; see [router-199-findings.md](router-199-findings.md).

## Related

- Routing / escalation design and earlier harness matrix: reuse ideas from the routing test plan and [docs/perf/config-search-plan.md](../perf/config-search-plan.md) (launch-status protocol, name+version labels).
- Multi-engine same-role graph work: [#150](https://github.com/brianreborn/familia/issues/150)
- Swarm process: [#151](https://github.com/brianreborn/familia/issues/151)
