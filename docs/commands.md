# Every familia command

This page mirrors `scripts/menu-items.txt`, the same table `./familia` and `familia.cmd` read; `tests/test_menu.py` checks this page lists every item.
Run any row from the menu, or directly with `./familia-menu.sh --run KEY [ARG...]` (Windows: `familia.cmd -Run KEY`). Add `--dry-run` to see the command without running it.
`<NAME>` is asked for when you pick the item. "licenses first" means `scripts/licenses.py gate` runs before it ([licenses.md](licenses.md)).


## Set up

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `setup.panel` | Configure in a simple window (mouse, keyboard or switch friendly) ([panel.md](panel.md)) | `python3 scripts/panel.py` | `python scripts\panel.py` |
| `setup.configure` | Get or update the pinned parts (code-bootstraps, green-agentz, ...) (licenses first) | `sh scripts/configure.sh` | - |
| `setup.licenses` | Review the licenses of everything you have chosen | `python3 scripts/licenses.py review` | `python scripts\licenses.py review` |
| `setup.settings` | Change launcher settings (port, threads, context) on the terminal | `sh scripts/configure.sh --interactive` | - |
| `setup.install` | Install or update this host (llama.cpp runtime, host entry): dry run first | `sh install/linux/install.sh --dry-run` | `powershell -NoProfile -ExecutionPolicy Bypass -File install\windows\install.ps1 -DryRun` |
| `setup.install-run` | Install or update this host for real (asks you to accept licenses) | `sh install/linux/install.sh` | `powershell -NoProfile -ExecutionPolicy Bypass -File install\windows\install.ps1` |
| `setup.logon-task` | Windows: start the model server at logon (preview; drop -WhatIf to register) | Windows only | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-task.ps1 -Install -Model <MODEL> -WhatIf` |

## Skills

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `skills.menu` | Bundled skills: switch skills on/off for an agent (license-checked) | `python3 scripts/skills.py menu --agent <AGENT>` | `python scripts\skills.py menu --agent <AGENT>` |
| `skills.list` | List every skill with its license and status | `python3 scripts/skills.py list` | `python scripts\skills.py list` |
| `skills.show` | Show one skill: license, where it lives, what it adds | `python3 scripts/skills.py show <SKILL>` | `python scripts\skills.py show <SKILL>` |
| `skills.vendor` | Show the plan to bring a survey skill into green-zkillz (no changes) | `python3 scripts/skills.py vendor <SKILL> --dry-run` | `python scripts\skills.py vendor <SKILL> --dry-run` |
| `skills.validate` | Check the skills catalog and the skills in graph.yaml | `python3 scripts/skills.py validate` | `python scripts\skills.py validate` |

## Models

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `models.add` | Add a model from a Hugging Face folder or a .gguf (dry run) | `scripts/add-model.sh <PATH> --dry-run` | `python scripts\add_model.py <PATH> --dry-run` |
| `models.add-apply` | Add a model from a folder or .gguf for real (writes manifest and preset) | `scripts/add-model.sh <PATH>` | `python scripts\add_model.py <PATH>` |
| `models.fetch-preview` | Download a model from Hugging Face: preview (no download) | `scripts/add-model.sh --fetch <REPO> --quant <QUANT> --dry-run` | `python scripts\add_model.py --fetch <REPO> --quant <QUANT> --dry-run` |
| `models.fetch` | Download and add a model from Hugging Face (asks you to accept its license) | `scripts/add-model.sh --fetch <REPO> --quant <QUANT>` | `python scripts\add_model.py --fetch <REPO> --quant <QUANT>` |
| `models.cards` | Fetch only a model's card, config and license (no weights) | `python3 scripts/hf_fetch.py <REPO> --damp-run` | `python scripts\hf_fetch.py <REPO> --damp-run` |
| `models.license` | Show one model's license and what it obliges you to | `python3 scripts/model_license.py show <ID>` | `python scripts\model_license.py show <ID>` |
| `models.check` | Check graph.yaml: models, RAM budget, required launch parameters | `python3 scripts/validate_graph.py --graph graph.yaml` | `python scripts\validate_graph.py --graph graph.yaml` |
| `models.explain` | Show the exact launch parameters for one node | `python3 scripts/validate_graph.py --graph graph.yaml --explain <NODE>` | `python scripts\validate_graph.py --graph graph.yaml --explain <NODE>` |
| `models.licenses` | List model, skill and engine licenses (records nothing) | `python3 scripts/licenses.py list` | `python scripts\licenses.py list` |

## Agents (hermes)

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `agents.hermes-model` | Hermes: single model (pick model) (licenses first; not available until `scripts/hermes_harness.py` lands) | `scripts/hermes.sh --model <MODEL>` | - |
| `agents.hermes-graph` | Hermes: full graph (licenses first; not available until `scripts/hermes_harness.py` lands) | `scripts/hermes.sh --graph-mode` | - |
| `agents.hermes` | Hermes on the graph coder node (64K context) (licenses first) | `scripts/hermes.sh` | - |
| `agents.hermes-render` | Write the hermes config only; start nothing | `scripts/hermes.sh --render-only` | - |
| `agents.fleet-test` | Launch-test a role: validate, would-start, stop | `sh with-fleet.sh --role <ROLE> --launch-test` | - |
| `agents.fleet` | Launch a role from graph.yaml (pentest roles are only launch-tested) (licenses first) | `sh with-fleet.sh --role <ROLE>` | - |

## Self-improving harness (Harness2)

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `harness2.status` | Show which agents have Harness2 and in which mode (not available until `scripts/harness2.py` lands) | `python3 scripts/harness2.py status` | `python scripts\harness2.py status` |
| `harness2.set` | Choose target agent and mode (off / propose / apply) (licenses first; not available until `scripts/harness2.py` lands) | `python3 scripts/harness2.py set --agent <AGENT> --mode <MODE>` | `python scripts\harness2.py set --agent <AGENT> --mode <MODE>` |
| `harness2.review` | Review proposals: list, accept or revert (not available until `scripts/harness2.py` lands) | `python3 scripts/harness2.py review` | `python scripts\harness2.py review` |

## Test & benchmark

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `test.unit` | Run the unit tests (installs pytest into .cache/pylib once) | `sh scripts/run-tests.sh` | - |
| `test.offline` | Offline test plan (prints live steps; RUN=1 to run them) | `bash scripts/offline-test-plan.sh` | - |
| `test.registry` | Benchmark records: best measured model per host and role | `python3 scripts/registry.py suggest --host <HOST> --role <ROLE>` | `python scripts\registry.py suggest --host <HOST> --role <ROLE>` |
| `test.registry-summary` | Summary of every benchmark record | `python3 scripts/registry.py summarize` | `python scripts\registry.py summarize` |

## Hosts

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `hosts.monitor` | Monitor hosts over SSH (read-only console; --once for one snapshot) | `sh familia-monitor` | `python scripts\monitor.py` |
| `hosts.monitor-once` | One snapshot of every host, then exit | `sh familia-monitor --once` | `python scripts\monitor.py --once` |
| `hosts.start` | Start the model server on this machine (licenses first) | `sh start.sh` | `scripts\windows\start.bat` |
| `hosts.serve` | Start one graph node's model server (exact launch parameters from the graph) (licenses first) | `sh scripts/serve.sh <NODE>` | - |
| `hosts.measure` | Measure this machine for graph.yaml (dry run) | `python3 scripts/host_measure.py --name <HOST> --dry-run` | - |
| `hosts.measure-write` | Measure this machine and write it into graph.yaml | `python3 scripts/host_measure.py --name <HOST>` | `python scripts\host_measure.py --name <HOST>` |
| `hosts.generate` | Write a per-host graph to generated/graph-HOST.yaml | `python3 scripts/generate_graph.py <HOST>` | `python scripts\generate_graph.py <HOST>` |
| `hosts.android` | Start the node on an Android phone over SSH (licenses first) | `bash android_start.sh <HOST>` | - |
| `hosts.phones` | Start every phone listed in graph.yaml (licenses first) | `bash android_multi_start.sh` | - |
| `hosts.watchdog` | Keep a phone's node running (restart it if it stops answering) (licenses first) | `bash watchdog_android.sh <HOST>` | - |

## Advanced: models & graph

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `adv.args` | validate_graph: the llama-server arguments for one node | `python3 scripts/validate_graph.py --graph graph.yaml --args <NODE>` | `python scripts\validate_graph.py --graph graph.yaml --args <NODE>` |
| `adv.verify` | validate_graph: also verify model sha256 and runtimes (slow) | `python3 scripts/validate_graph.py --graph graph.yaml --verify-sha --check-runtimes` | `python scripts\validate_graph.py --graph graph.yaml --verify-sha --check-runtimes` |
| `adv.graph-edit` | modify_graph: assign a model to a node (preview; a real run drops graph.yaml comments) | `python3 scripts/modify_graph.py --assign-model <ASSIGN> --dry-run` | `python scripts\modify_graph.py --assign-model <ASSIGN> --dry-run` |
| `adv.db-list` | Model database: list entries | `python3 scripts/model_db.py list` | `python scripts\model_db.py list` |
| `adv.db-show` | Model database: show one entry | `python3 scripts/model_db.py show <ID>` | `python scripts\model_db.py show <ID>` |
| `adv.db-damp` | Model database: add a repo without weights (preview) | `python3 scripts/model_db.py damp <REPO> --dry-run` | `python scripts\model_db.py damp <REPO> --dry-run` |
| `adv.db-backfill` | Model database: backfill entries for models in the manifest (preview) | `python3 scripts/model_db.py backfill --dry-run` | `python scripts\model_db.py backfill --dry-run` |
| `adv.llama-flags` | llama_flags: does a pinned llama.cpp build have a flag? | `python3 scripts/llama_flags.py show <BUILD> <FLAG>` | `python scripts\llama_flags.py show <BUILD> <FLAG>` |
| `adv.scale-down` | Scale-down (opt-in smaller models): preview | `python3 scripts/scale_down.py --dry-run` | `python scripts\scale_down.py --dry-run` |
| `adv.licenses-json` | All licenses as JSON (records nothing) | `python3 scripts/licenses.py list --json` | `python scripts\licenses.py list --json` |

## Advanced: agents

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `adv.skills-paths` | Folders of the skills enabled for an agent | `python3 scripts/skills.py paths --agent <AGENT>` | `python scripts\skills.py paths --agent <AGENT>` |
| `adv.hermes-selftest` | Hermes: check that context compaction keeps facts (licenses first) | `scripts/hermes.sh --selftest-compaction` | - |
| `adv.hermes-escalate` | Hermes with escalation to a bigger model when stuck (licenses first) | `scripts/hermes.sh --escalate` | - |
| `adv.escalate-accept` | Escalation: accept the pending suggestion | `python3 scripts/escalate.py accept` | `python scripts\escalate.py accept` |
| `adv.escalate-consent` | Escalation: allow a node to hand off to another host | `python3 scripts/escalate.py consent --node <NODE> --target <TARGET>` | `python scripts\escalate.py consent --node <NODE> --target <TARGET>` |

## Advanced: hosts & benchmarks

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `adv.registry-query` | Benchmark records for one host | `python3 scripts/registry.py query --host <HOST>` | `python scripts\registry.py query --host <HOST>` |
| `adv.registry-match` | Hardware profile that matches a host | `python3 scripts/registry.py match --graph graph.yaml --host <HOST>` | `python scripts\registry.py match --graph graph.yaml --host <HOST>` |
| `adv.registry-power` | Power use recorded per host | `python3 scripts/registry.py power` | `python scripts\registry.py power` |
| `adv.registry-lint` | Check the benchmark records | `python3 scripts/registry.py lint` | `python scripts\registry.py lint` |
| `adv.power-probe` | One power reading of this machine (read-only) | `sh scripts/power_probe.sh <SECONDS>` | - |
| `adv.cpu-level` | This CPU's x86-64 level and the numpy it needs | `python3 scripts/cpu_level.py` | `python scripts\cpu_level.py` |
| `adv.phone-target` | Phones in graph.yaml and how they are reached | `python3 scripts/android_target.py --list` | `python scripts\android_target.py --list` |
| `adv.monitor-deaths` | Monitor: alert on crashed or killed model servers | `sh familia-monitor --watch-deaths` | `python scripts\monitor.py --watch-deaths` |
| `adv.c2c-loopback` | C2C test: move a KV cache between two local servers | `sh scripts/c2c/loopback_test.sh <SERVER> <GGUF>` | - |
| `adv.uninstall` | Uninstall from this host: preview (models are kept) | `sh install/linux/install.sh --uninstall --dry-run` | `powershell -NoProfile -ExecutionPolicy Bypass -File install\windows\install.ps1 -Uninstall -DryRun` |
| `adv.logon-task-remove` | Windows: remove the logon task | Windows only | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-task.ps1 -Uninstall` |
| `adv.numpy-wheel` | Windows: build numpy for CPUs without SSE4 (long; needs MSYS2) | Windows only | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_numpy_wheel.ps1 -Version <VERSION>` |
| `adv.poudriere` | FreeBSD: build the familia package with poudriere (preview) | `sh scripts/freebsd/poudriere-build.sh -n` | - |

## Help

| key | what it does | Linux / Android | Windows |
|---|---|---|---|
| `help.quickstart` | Read the quick start | `more QUICKSTART.md` | `more QUICKSTART.md` |
| `help.cli` | Every menu item as a command (same as --list) | `./familia-menu.sh --list` | `familia.cmd -List` |
| `help.internal` | Scripts the menu leaves out on purpose, and why | `more scripts/menu-internal.txt` | `more scripts\menu-internal.txt` |

## Left out of the menu on purpose

These are called by other scripts or are developer-only. The list is `scripts/menu-internal.txt`; a new script must go in the menu or in that list, or the tests fail.

| script | why it's not in the menu |
|---|---|
| `install.sh` | bootstrap you run before familia is on disk (curl ... | sh); inside a checkout use Set up -> Install |
| `scripts/windows/familia-menu.ps1` | the Windows menu itself (started by familia.cmd) |
| `scripts/monitor.sh` | the same console as ./familia-monitor, which the menu runs |
| `scripts/hermes_harness.py` | always run through scripts/hermes.sh, which the menu runs |
| `install/windows/install.bat` | double-click wrapper for install\windows\install.ps1, which the Windows menu runs |
| `start-green-roomz.sh` | guard stub; the real one is deployed onto the phone by android_start.sh |
| `scripts/monitor/probe.py` | read-only probe the monitor pipes to each host over SSH |
| `scripts/monitor/probe.ps1` | Windows version of the probe the monitor pipes over SSH |
| `scripts/bench_parse.py` | filter for llama-bench output (pipe llama-bench -o csv into it); nothing to do on its own |
| `scripts/panel_familia.py` | familia's pages for the settings panel; loaded by scripts/panel.py, which the menu runs |
| `scripts/retry_wrapper.py` | library for agent model calls; its main is only a self-demo |
| `scripts/isolated/hfchat.py` | adapter that graph nodes of kind isolated_remote call; not run by hand |
| `scripts/c2c/kv_ship.py` | step of the C2C loopback test (Advanced menu), needs two running servers |
| `scripts/nexus/nexus.py` | SSH nexus proof of concept (#22); exercised by tests/test_nexus_localhost.sh |
| `scripts/bt/fetch.sh` | BitTorrent transport proof of concept; exercised by tests/test_bt_loopback.sh |
| `scripts/bt/seed.sh` | BitTorrent transport proof of concept; exercised by tests/test_bt_loopback.sh |
| `scripts/bt/tracker.py` | BitTorrent transport proof of concept; exercised by tests/test_bt_loopback.sh |
| `scripts/bt/mktorrent.py` | BitTorrent transport proof of concept; exercised by tests/test_bt_loopback.sh |
| `scripts/bt/key.py` | BitTorrent transport proof of concept; exercised by tests/test_bt_loopback.sh |
| `scripts/littlebit/convert.py` | LittleBit backend step; run through scale_down.py (Advanced menu) |
| `scripts/littlebit/lbref.py` | LittleBit reference runtime used by scale_down.py and its checks |
| `scripts/littlebit/check_ref.py` | LittleBit developer check against upstream PyTorch (needs torch) |
| `scripts/littlebit/hfllama.py` | LittleBit developer helper (needs transformers) |
| `scripts/littlebit/produce_tiny.py` | LittleBit pipeline exercise only (docs/littlebit.md) |
| `scripts/littlebit/lbformat.py` | LittleBit file format library |
