# Router R&D findings (#199)

Status: catalogue + offline test suite, 2026-10-30 (PT). Tests/plans only; no product code changed.
Suite: `tests/test_router_199.py` (fake loopback node servers + a fake gateway that serves the exact
manifest `scripts/start_graph.py` builds for green-roomz graph-proxy). Known no-op cases are
`xfail(strict=True)` with `#199` in the reason, so a fix turns them XPASS and the marker must be removed.
Hosts are graph.yaml keys only; no addresses, logins, ports or keys.

Run: `python3 -m pytest -q tests/test_router_199.py -rxX` → **8 passed, 18 xfailed**.

## 1. Expected routing per node TYPE (host = placement only)

| Request type (alias/model) | Must land on | Fallback | Never |
|---|---|---|---|
| `chat` | active node, role chat | none (refuse) | coder/decision |
| `coder` | active node, role coder (any engine; #150 instances by policy) | none | chat-only node |
| `general` | role general | role chat | coder (today it does) |
| `decision` | role decision (light, small) | none | heavy nodes |
| `reasoning` | role reasoning | none (refuse) | default node |
| `embed` | role embed with `--embeddings` | none | chat nodes |
| `guardian` / `pentest` | role guardian/pentest, launch-test-only | refuse loudly | any other |
| unknown | refuse (404) | — | silent default |

#150: a role alias may target ≥2 same-role instances (different engines); routing picks per
policy (competing / tandem / specialized / escalate). Matches the #119 suite's `multi_engine` tasks.

## 2. No-op catalogue

| # | Case (shape) | Expected | Actual | Root cause |
|---|---|---|---|---|
| 1 | graph mode, gateway host, `model=general` | general/chat node | coder node | `graph.yaml` aliases.general → coder (~l.927) |
| 2 | graph mode, gateway host, `model=chat` | chat node | 404 (no alias, no active chat node) | graph.yaml (angel-chat planned; phone8-general planned) |
| 3 | graph mode, `model=decision` | decision node | unroutable; graph-proxy refuses role | `scripts/start_graph.py:168-172` (only chat+embed) |
| 4 | alias → planned node (`safe-build`, `guardian`, `pentest`, `defender`) | route or loud error | silently omitted, warn only | `scripts/start_graph.py:147-149` |
| 5 | host with active nodes but no gateway (`box`, `angel`) | type routing | port-only; no router at all | graph.yaml gateways (one, on miryam) |
| 6 | hermes graph mode (agents hermes, hermes-lab) | per-task type routing | main+auxiliary pinned to one alias (`coder`) | graph.yaml agents.*.aliases; `scripts/hermes_harness.py:230` (owns `smart_model_routing`), `:488-500` |
| 7 | hermes single mode `--model NODE` | that node | that node (by design, no router) | `scripts/hermes_modes.py:8-10` — OK |
| 8 | escalation proxy auto-on for graph mode | proxy when main can escalate | never: main node `coder` has no `escalates_to` | `scripts/hermes_modes.py:218-221` + graph.yaml |
| 9 | escalation anywhere | ≥1 active escalating node | only planned nodes escalate | graph.yaml (qodesh-smol-cpu, miryam-gpu-decision planned) |
| 10 | escalation proxy `--escalate` with stuck signal | suggest/auto | suggest — OK | `scripts/escalation.py:160` |
| 11 | #150 two coder engines on one host | both reachable by role | alias is 1:1 → second instance unreachable by role | `scripts/graph_types.py` aliases (`node` ref single) |
| 12 | self-launched llama-server (installer `familia-start` / Termux launcher) | joins graph routing | standalone, single model, no alias, no gateway | `install/linux/install.sh:281`, `install/termux/install.sh:225` |
| 13 | code-bootstraps router mode (`start.sh --bootstrap`, models-preset.ini) | per-role model | not verified offline (pinned repo not checked out here); proto_chat treats router as 1 model | `scripts/proto_chat.sh:203-243`; see code-bootstraps-llama.cpp#26 |

**13 cases, 9 no-op** (1-6, 8, 9, 11; plus 12 is routing-absent by design and 13 unverified).

## 3. `--tools` on llama-server launch paths

`--tools` is only emitted when a node sets `server_tools` (`scripts/validate_graph.py:418-423`).

| Path | Explicit `--tools`? |
|---|---|
| `serve.sh` / `start_graph.py` → `validate_graph.py --args` for **angel-coder** | yes (`all`) |
| same, for **coder, embed, box-coder, box-decision, qodesh-resident** (all other active llama-server nodes) | **no** |
| `install/linux/install.sh:281` familia-start exec (also the systemd unit) | **no** |
| `install/termux/install.sh:225` launcher | **no** |
| `scripts/serve.sh` CPU fallback re-exec | inherits node args (same as above) |
| `scripts/launch_matrix.py`, `scripts/perf/spec_bench.py` (bench only) | no (bench; acceptable but should be explicit `--tools` none/"" when supported) |
| code-bootstraps router + children | not checked here (pinned repo; router-child-no-tools patch was dropped per #199) |

Note: for `embed` an explicit empty/none tools setting is the right answer, not `all`.

## 4. Hook into #119

These cases are routing acceptance for #119 (`docs/testing/task-suite-acceptance.md`): a router or
alias change is a radical change; the strict xfails must flip to pass before promotion.
