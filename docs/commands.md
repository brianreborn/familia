# Every familia command

This page mirrors `scripts/menu-items.txt` (legacy catalog). Default `./familia` opens the Charm/gum home (`scripts/familia_home.sh`); use `./familia menu` / `--legacy-menu` for this catalog. `tests/test_menu.py` checks this page lists every item.
Run any row from the legacy menu, as a command (`./familia COMMAND`, below), or with `./familia run KEY [ARG...]` (Windows: `familia.cmd run KEY`). Add `--dry-run` before a command to print it without running (CLI mode only — items themselves are real runs).
`<NAME>` is asked for when you pick the item. "licenses first" means `scripts/licenses.py gate` runs before it ([licenses.md](licenses.md)).

## Command line

Every row is also a command: `./familia COMMAND [VALUE...] [ARG...]` (Windows: `familia.cmd COMMAND ...`). It runs the identical command, with the same license review, as picking it in the menu. `./familia help` lists every command by group; `./familia help COMMAND` or `./familia COMMAND --help` shows what one runs and then the script's own `--help`. The full manual is `man ./man/familia.1` (or `./familia help --man`).

```
./familia skills list                  # = Skills > List every skill
./familia model params coder           # <NODE> = coder
./familia harness2 set --agent hermes --mode propose   # values by the flag they follow, or in order
./familia --dry-run serve coder        # print the command (and the license step), run nothing
./familia monitor --once HOST          # anything after the values goes to the script
./familia skills enable green-probe    # pass-through: any skills.py / licenses.py / harness2.py / registry.py command
./familia FOO=bar BAR=x model fetch org/name --quant Q4_K_M
eval "$(./familia completion bash)"    # tab completion in bash
```

Names come from `scripts/cli-commands.txt` (natural names such as `model add`, `host measure`). Every row also gets automatic ones: its key (`models.explain`), `GROUP NAME` (`models explain`), and the short name when it is unique (`explain`), so a new row in `scripts/menu-items.txt` is a command and is in `familia help` and the man page at once. After adding a row, regenerate the man page: `python3 scripts/familia_cli.py man --write` (`tests/test_cli.py` checks it is current). Leading `NAME=value` assignments are exported for the selected command. Options for familia itself go before the command (`--dry-run`, `--yes`, `--pipe`); after the command everything goes to the script, so `./familia install --dry-run` is the installer's own preview and `./familia install --branch BRANCH` selects its familia checkout branch. On FreeBSD, the runtime installer is intentionally unsupported; use `./familia sync --branch BRANCH` and the source-build instructions below. At a numbered menu item prompt, enter `NAME=value 6 --baz` to set an environment variable and pass remaining arguments to that item. A value that has no default and is not given is asked for on a terminal; without one the command stops with exit status 2 and says which value it needs.


## Search

At any menu prompt, type `/` and a word to search every group: item keys, labels, commands and group names, ignoring case. `?word` searches backward (the last match is marked first). `n` goes to the next match and `N` to the previous one, wrapping around, and `/` alone repeats the last search. Pick a result by its number: it runs exactly like picking it from its group, with the same license review, dry-run and prompts for values. Matches are highlighted when the terminal supports it (`NO_COLOR=1` or `FAMILIA_COLOR=never` turns that off).

Without the interactive menu, for scripts or when typing is hard:

```
./familia search WORD                      # or: ./familia-menu.sh --search WORD
./familia search WORD --run N [VALUE...]   # run match N (add --dry-run to only print it)
familia.cmd -Search WORD [-Run N] [-DryRun]
```

`--search` exits 0 when something matched and 1 when nothing did.

## Recommended paths

The interactive menu and `--list` show these paths before the command groups. Follow the route for your goal; the listed commands still need their usual inputs, installed dependencies, and license acceptance.

| goal | path |
|---|---|
| Set up a new checkout and start its local server | `setup.first-time` (deps → licenses → configure → install → PATH) then `hosts.start` |
| Start a graph node | `models.check` -> `hosts.serve <NODE>` |
| Add and launch a model | `models.fetch` -> add its node to `graph.yaml` -> `models.check` -> `hosts.serve <NODE>` (or gum home → Find more models) |
| Run Hermes on the graph coder | `models.check` -> `agents.hermes` (license-gated) |

**Not done yet:** the FreeBSD llama.cpp 0.7.0 build and model-load smoke test on `angel` have not been run, and `angel` is measured in `graph.yaml` but still has no active nodes. FreeBSD currently has no package-based setup here: do not run `familia install` or install packages; build the pinned llama.cpp checkout from source using the already available toolchain. From `code-bootstraps-llama.cpp`, run `BUILD_DIR=build-freebsd GPU=off scripts/build-linux.sh`, then verify `build-freebsd/bin/llama-server --version`. Planned Nanbeige nodes need the GGUF on disk before `status: active`.

## Menu items by group (legacy catalog)

Default front door is the gum home (`./familia`). This catalog is **fallback only**.

### Set up

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `setup.first-time` | First-time setup on this machine (deps → licenses → install → PATH) | `sh scripts/setup_goals.sh first-time` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\setup-goals.ps1 -Goal first-time` |
| `setup.update` | Update this checkout (git pull --ff-only, then sync pins) | `python3 scripts/sync_pins.py --update` | `python scripts\sync_pins.py --update` |
| `setup.licenses` | Review / accept licenses | `python3 scripts/licenses.py review` | `python scripts\licenses.py review` |
| `setup.settings` | Change launcher settings (terminal) | `sh scripts/configure.sh --interactive` | — |
| `setup.sync-goal` | Sync pinned parts only (asks preview vs apply) | `sh scripts/setup_goals.sh sync-pins` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\setup-goals.ps1 -Goal sync-pins` |
| `setup.safe-build` | Safe-mode / offline build help | `sh scripts/safe-build-help.sh` | `powershell -NoProfile -Command "Write-Host (Get-Content -Raw docs\safe-mode-bootstrap.md)"` |
| `setup.logon-task` | Windows: start the model server at logon (registers the task) | — | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-task.ps1 -Install -Model <MODEL>` |
| `setup.remove-path` | Remove familia from PATH (danger; ) | `sh scripts/setup_goals.sh remove-path` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\setup-goals.ps1 -Goal remove-path` |

### Skills

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `skills.menu` | Bundled skills: switch skills on/off for an agent (license-checked) | `python3 scripts/skills.py menu --agent <AGENT>` | `python scripts\skills.py menu --agent <AGENT>` |
| `skills.list` | List every skill with its license and status | `python3 scripts/skills.py list` | `python scripts\skills.py list` |
| `skills.show` | Show one skill: license, where it lives, what it adds | `python3 scripts/skills.py show <SKILL>` | `python scripts\skills.py show <SKILL>` |
| `skills.vendor` | Bring a survey skill into green-zkillz | `python3 scripts/skills.py vendor <SKILL>` | `python scripts\skills.py vendor <SKILL>` |
| `skills.validate` | Check the skills catalog and the skills in graph.yaml | `python3 scripts/skills.py validate` | `python scripts\skills.py validate` |

### Reach tools (Agent-Reach)

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `reach.status` | Agent-Reach: pin checkout, CLI, which agents are opted in | `python3 scripts/agent_reach.py status` | `python scripts\agent_reach.py status` |
| `reach.enable` | Opt an agent into Agent-Reach (writes reaches: in graph.yaml) | `python3 scripts/agent_reach.py enable --agent <AGENT>` | `python scripts\agent_reach.py enable --agent <AGENT>` |
| `reach.disable` | Remove an agent from Agent-Reach | `python3 scripts/agent_reach.py disable --agent <AGENT>` | `python scripts\agent_reach.py disable --agent <AGENT>` |
| `reach.link` | Link Agent-Reach skill + CLI wrapper into an agent's HERMES_HOME | `python3 scripts/agent_reach.py link --agent <AGENT>` | `python scripts\agent_reach.py link --agent <AGENT>` |
| `reach.mcp` | Print mcpServers JSON for llama UI / code-bootstraps | `python3 scripts/agent_reach.py mcp-example` | `python scripts\agent_reach.py mcp-example` |

### Models

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `models.add` | Add a model from a Hugging Face folder or a .gguf | `scripts/add-model.sh <PATH>` | `python scripts\add_model.py <PATH>` |
| `models.fetch` | Download and add a model from Hugging Face (asks you to accept its license) | `scripts/add-model.sh --fetch <REPO> --quant <QUANT>` | `python scripts\add_model.py --fetch <REPO> --quant <QUANT>` |
| `models.cards` | Fetch only a model's card, config and license (no weights) | `python3 scripts/hf_fetch.py <REPO> --damp-run` | `python scripts\hf_fetch.py <REPO> --damp-run` |
| `models.license` | Show one model's license and what it obliges you to | `python3 scripts/model_license.py show <ID>` | `python scripts\model_license.py show <ID>` |
| `models.check` | Check graph.yaml: models, RAM budget, required launch parameters | `python3 scripts/validate_graph.py --graph graph.yaml` | `python scripts\validate_graph.py --graph graph.yaml` |
| `models.explain` | Show the exact launch parameters for one node | `python3 scripts/validate_graph.py --graph graph.yaml --explain <NODE>` | `python scripts\validate_graph.py --graph graph.yaml --explain <NODE>` |
| `models.licenses` | List model, skill and engine licenses (records nothing) | `python3 scripts/licenses.py list` | `python scripts\licenses.py list` |

### Agents (hermes)

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `agents.hermes-model` | Hermes: single model (pick model) | `scripts/hermes.sh --model <MODEL>` | — |
| `agents.hermes-graph` | Hermes: full graph | `scripts/hermes.sh --graph-mode` | — |
| `agents.hermes` | Hermes on the graph coder node (64K context) | `scripts/hermes.sh` | — |
| `agents.hermes-render` | Write the hermes config only; start nothing | `scripts/hermes.sh --render-only` | — |
| `agents.fleet-test` | Launch-test a role: validate, would-start, stop | `sh with-fleet.sh --role <ROLE> --launch-test` | — |
| `agents.fleet` | Launch a role from graph.yaml (guardian/defender: seatbelts on by default) | `sh with-fleet.sh --role <ROLE>` | — |
| `agents.guardian-launch-test` | Guardian/defender: launch-test (seatbelts on) | `sh with-fleet.sh --role guardian --launch-test` | — |
| `agents.guardian-start` | Guardian/defender: operator-confirmed model start (tools empty) | `env FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh --role guardian --operator-start` | — |
| `agents.guardian-weights` | Guardian: dry-run fetch/measure/activate path (Dolphin3 Q2_K; no seatbelt edits) | `python3 scripts/activate_guardian_weights.py` | — |
| `agents.pentest-launch-test` | Legacy id → guardian launch-test | `sh with-fleet.sh --role guardian --launch-test` | — |
| `agents.pentest-start` | Legacy id → guardian operator-start | `env FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh --role guardian --operator-start` | — |

### Self-improving harness (Harness2)

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `harness2.status` | Show which agents have Harness2 and in which mode | `python3 scripts/harness2.py status` | `python scripts\harness2.py status` |
| `harness2.set` | Set Harness² mode for any agent (hermes, llama UI, or other; off / propose / apply) | `python3 scripts/harness2.py set --agent <AGENT> --mode <MODE>` | `python scripts\harness2.py set --agent <AGENT> --mode <MODE>` |
| `harness2.review` | Review proposals: list, accept or revert | `python3 scripts/harness2.py review` | `python scripts\harness2.py review` |
| `harness2.terminal-rsi` | Terminal-RSI round for a harness target (proposals only; review with harness2.review) | `python3 scripts/terminal_rsi.py --target <TARGET>` | `python scripts\terminal_rsi.py --target <TARGET>` |

### Test & benchmark

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `test.unit` | Run the unit tests (installs pytest into .cache/pylib once) | `sh scripts/run-tests.sh` | — |
| `ops.offline-improve` | Offline perf loop when fleet peers unreachable | `python3 scripts/offline_improve.py --loop` | — |
| `test.offline` | Offline test plan (prints live steps; RUN=1 to run them) | `bash scripts/offline-test-plan.sh` | — |
| `test.registry` | Benchmark records: best measured model per host and role | `python3 scripts/registry.py suggest --host <HOST> --role <ROLE>` | `python scripts\registry.py suggest --host <HOST> --role <ROLE>` |
| `test.registry-summary` | Summary of every benchmark record | `python3 scripts/registry.py summarize` | `python scripts\registry.py summarize` |
| `test.offline-secbench` | Opt-in offline security-model benches (#117); synthetic fixtures only | `env FAMILIA_OFFLINE_SECBENCH=1 python3 scripts/offline_secbench.py --platform <PLATFORM> --answers-dir <DIR>` | `set FAMILIA_OFFLINE_SECBENCH=1&& python scripts\offline_secbench.py --platform <PLATFORM> --answers-dir <DIR>` |

### Hosts

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `hosts.monitor` | Monitor hosts over SSH (read-only console; --once for one snapshot) | `sh familia-monitor` | `python scripts\monitor.py` |
| `hosts.monitor-once` | One snapshot of every host, then exit | `sh familia-monitor --once` | `python scripts\monitor.py --once` |
| `hosts.start` | Start the model server on this machine from graph.yaml | `sh start.sh` | `scripts\windows\start.bat` |
| `hosts.serve` | Start one graph node's model server (exact launch parameters from the graph) | `sh scripts/serve.sh <NODE>` | — |
| `hosts.measure-write` | Measure and write this host (identify kind; GPU inventory stays unknown until measured) | `python3 scripts/host_measure.py --name <HOST> --kind <KIND> --force` | `python scripts\host_measure.py --name <HOST> --kind <KIND> --force` |
| `hosts.pin` | Pin this machine's graph host name (menus/start auto-use it) | `python3 scripts/hostname_pin.py set <HOST>` | `python scripts\hostname_pin.py set <HOST>` |
| `hosts.pin-show` | Show pinned graph host (or empty) | `python3 scripts/hostname_pin.py get` | `python scripts\hostname_pin.py get` |
| `hosts.generate` | Write a per-host graph to generated/graph-HOST.yaml | `python3 scripts/generate_graph.py <HOST>` | `python scripts\generate_graph.py <HOST>` |
| `hosts.android` | Start the node on an Android phone over SSH | `bash android_start.sh <HOST>` | — |
| `hosts.phones` | Start every phone listed in graph.yaml | `bash android_multi_start.sh` | — |
| `hosts.watchdog` | Keep a phone's node running (restart it if it stops answering) | `bash watchdog_android.sh <HOST>` | — |
| `hosts.phone-agents` | Phone assistants (Bixby, Gemini): which are set up and what leaves the phone | `python3 scripts/system_agents.py status` | `python scripts\system_agents.py status` |
| `hosts.phone-agents-licenses` | Phone assistants: Shizuku license and the terms each assistant brings | `python3 scripts/system_agents.py licenses` | `python scripts\system_agents.py licenses` |
| `hosts.phone-agent-probe` | On this phone (Termux): is Shizuku running, which assistants are installed | `python3 scripts/termux/system_agent.py probe` | — |
| `hosts.phone-agent-open` | On this phone: bring Gemini or Bixby to the front (sends nothing) | `python3 scripts/termux/system_agent.py open --provider <PROVIDER>` | — |
| `hosts.phone-agent-ask` | On this phone: ask Gemini (CLOUD: your text goes to Google; asks first) | `python3 scripts/termux/system_agent.py ask --provider gemini --text <TEXT>` | — |
| `hosts.phone-agent-consent` | On this phone: allow or withdraw cloud calls to an assistant | `python3 scripts/termux/system_agent.py consent --provider <PROVIDER> <CHOICE>` | — |

### Advanced: models & graph

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `adv.args` | validate_graph: the llama-server arguments for one node | `python3 scripts/validate_graph.py --graph graph.yaml --args <NODE>` | `python scripts\validate_graph.py --graph graph.yaml --args <NODE>` |
| `adv.verify` | validate_graph: also verify model sha256 and runtimes (slow) | `python3 scripts/validate_graph.py --graph graph.yaml --verify-sha --check-runtimes` | `python scripts\validate_graph.py --graph graph.yaml --verify-sha --check-runtimes` |
| `adv.graph-edit` | modify_graph: assign a models: key to a type-named node | `python3 scripts/modify_graph.py --host angel --assign-model coder=nanbeige43-33b-q4km` | `python scripts\modify_graph.py --host angel --assign-model coder=nanbeige43-33b-q4km` |
| `adv.db-list` | Model database: list entries | `python3 scripts/model_db.py list` | `python scripts\model_db.py list` |
| `adv.db-show` | Model database: show one entry | `python3 scripts/model_db.py show <ID>` | `python scripts\model_db.py show <ID>` |
| `adv.db-damp` | Model database: add a repo without weights (damp) | `python3 scripts/model_db.py damp <REPO>` | `python scripts\model_db.py damp <REPO>` |
| `adv.db-backfill` | Model database: backfill entries for models in the manifest | `python3 scripts/model_db.py backfill` | `python scripts\model_db.py backfill` |
| `adv.llama-flags` | llama_flags: does a pinned llama.cpp build have a flag? | `python3 scripts/llama_flags.py show <BUILD> <FLAG>` | `python scripts\llama_flags.py show <BUILD> <FLAG>` |
| `adv.scale-down` | Scale-down (opt-in smaller models) — apply | `python3 scripts/scale_down.py` | `python scripts\scale_down.py` |
| `adv.licenses-json` | All licenses as JSON (records nothing) | `python3 scripts/licenses.py list --json` | `python scripts\licenses.py list --json` |

### Advanced: agents

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `adv.skills-paths` | Folders of the skills enabled for an agent | `python3 scripts/skills.py paths --agent <AGENT>` | `python scripts\skills.py paths --agent <AGENT>` |
| `adv.hermes-selftest` | Hermes: check that context compaction keeps facts | `scripts/hermes.sh --selftest-compaction` | — |
| `adv.hermes-escalate` | Hermes with escalation to a bigger model when stuck | `scripts/hermes.sh --escalate` | — |
| `adv.escalate-accept` | Escalation: accept the pending suggestion | `python3 scripts/escalate.py accept` | `python scripts\escalate.py accept` |
| `adv.escalate-consent` | Escalation: allow a node to hand off to another host | `python3 scripts/escalate.py consent --node <NODE> --target <TARGET>` | `python scripts\escalate.py consent --node <NODE> --target <TARGET>` |

### Advanced: hosts & benchmarks

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `adv.registry-query` | Benchmark records for one host | `python3 scripts/registry.py query --host <HOST>` | `python scripts\registry.py query --host <HOST>` |
| `adv.registry-match` | Hardware profile that matches a host | `python3 scripts/registry.py match --graph graph.yaml --host <HOST>` | `python scripts\registry.py match --graph graph.yaml --host <HOST>` |
| `adv.registry-power` | Power use recorded per host | `python3 scripts/registry.py power` | `python scripts\registry.py power` |
| `adv.registry-lint` | Check the benchmark records | `python3 scripts/registry.py lint` | `python scripts\registry.py lint` |
| `adv.power-probe` | One power reading of this machine (read-only) | `sh scripts/power_probe.sh <SECONDS>` | — |
| `adv.cpu-level` | This CPU's x86-64 level and the numpy it needs | `python3 scripts/cpu_level.py` | `python scripts\cpu_level.py` |
| `adv.phone-target` | Phones in graph.yaml and how they are reached | `python3 scripts/android_target.py --list` | `python scripts\android_target.py --list` |
| `adv.monitor-deaths` | Monitor: alert on crashed or killed model servers | `sh familia-monitor --watch-deaths` | `python scripts\monitor.py --watch-deaths` |
| `adv.c2c-loopback` | C2C test: move a KV cache between two local servers | `sh scripts/c2c/loopback_test.sh <SERVER> <GGUF>` | — |
| `adv.uninstall` | Uninstall from this host (models are kept) | `sh `INSTALLER` --uninstall` | `powershell -NoProfile -ExecutionPolicy Bypass -File install\windows\install.ps1 -Uninstall` |
| `adv.logon-task-remove` | Windows: remove the logon task | — | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-task.ps1 -Uninstall` |
| `adv.numpy-wheel` | Windows: build numpy for CPUs without SSE4 (long; needs MSYS2) | — | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_numpy_wheel.ps1 -Version <VERSION>` |
| `adv.poudriere` | FreeBSD: build the familia package with poudriere | `sh scripts/freebsd/poudriere-build.sh` | — |
| `setup.configure` | Low-level: set up this checkout (sync pins + git-pull hooks) | `sh scripts/configure.sh` | — |
| `setup.sync` | Low-level: bring every pinned part to its pin | `python3 scripts/sync_pins.py` | `python scripts\sync_pins.py` |
| `setup.deps` | Low-level: install local OS packages this host needs | `sh install/deps.sh --install` | `powershell -NoProfile -ExecutionPolicy Bypass -File install\windows\deps.ps1 -Install` |
| `setup.install` | Low-level: install or update this host for real | `sh `INSTALLER`` | `powershell -NoProfile -ExecutionPolicy Bypass -File install\windows\install.ps1` |
| `setup.install-cli` | Low-level: put familia on PATH for real | `sh scripts/install-cli.sh` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-cli.ps1` |
| `setup.path-add` | Low-level: add ~/.local/bin to PATH in ~/.profile | `sh scripts/install-cli.sh path --add` | — |
| `setup.path-remove` | Low-level: remove familia PATH block from ~/.profile | `sh scripts/install-cli.sh path --remove` | — |
| `setup.cli-status` | Low-level: show where familia is on PATH | `sh scripts/install-cli.sh status` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-cli.ps1 -Status` |
| `setup.uninstall-cli` | Low-level: take familia off PATH (asks first) | `sh scripts/install-cli.sh uninstall` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-cli.ps1 -Uninstall` |

### ★ Required checks (must-run)

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `test.required` | ★ Run ALL three critical bash smokes for real (fleet + nexus + bt) | `sh scripts/required_checks.sh` | — |

### Help

| Key | Label | POSIX | Windows |
|---|---|---|---|
| `help.quickstart` | Read the quick start | `QUICKSTART.md` | `more QUICKSTART.md` |
| `help.search` | Search every group for a word (in the menu: /word, then n / N) | `./familia-menu.sh --search <WORD>` | `familia.cmd -Search <WORD>` |
| `help.cli` | Every menu item as a command (same as --list) | `./familia-menu.sh --list` | `familia.cmd -List` |
| `help.man` | The familia(1) manual: every command, option, setting and file | `./familia help --man` | — |
| `help.internal` | Scripts the menu leaves out on purpose, and why | `scripts/menu-internal.txt` | `more scripts\menu-internal.txt` |

## Left out of the menu on purpose

These are called by other scripts or are developer-only. The list is `scripts/menu-internal.txt`; a new script must go in the menu or in that list, or the tests fail.

| script | why it's not in the menu |
|---|---|
| `install.sh` | bootstrap you run before familia is on disk (download, then sh ./install-familia.sh); inside a checkout use Set up -> Install |
| `scripts/windows/familia-menu.ps1` | the Windows menu itself (started by familia.cmd) |
| `scripts/monitor.sh` | the same console as ./familia-monitor, which the menu runs |
| `scripts/hermes_harness.py` | always run through scripts/hermes.sh, which the menu runs |
| `scripts/hermes_modes.py` | the graph/single-model front end scripts/hermes.sh execs; run hermes.sh |
| `install/windows/install.bat` | double-click wrapper for install\windows\install.ps1, which the Windows menu runs |
| `start-green-roomz.sh` | guard stub; the real one is deployed onto the phone by android_start.sh |
| `scripts/monitor/probe.py` | read-only probe the monitor pipes to each host over SSH |
| `scripts/monitor/probe.ps1` | Windows version of the probe the monitor pipes over SSH |
| `scripts/bench_parse.py` | filter for llama-bench output (pipe llama-bench -o csv into it); nothing to do on its own |
| `scripts/bench_guard.py` | library for perf/bench drivers: GGUF metadata validation, current llama.cpp flag spellings, encoder ubatch rule, per-run memory cap (`meta FILE`, `memcap PEAK_MIB`) |
| `scripts/prompt_cache.py` | library: prefill an agent's fixed prompt prefix once, save it with llama-server slot save, restore it on later starts (#85); used by hermes.sh |
| `scripts/system_prompt_check.py` | offline system-prompt path checks (#115); developer/CI helper, not an end-user menu action |
| `scripts/offline_secbench.py` | opt-in offline security-model benches (#117); synthetic fixtures only; developer helper, not an end-user menu action |
| `scripts/familia_agent_reach.py` | thin wrapper / library around Agent-Reach; menu uses scripts/agent_reach.py |
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
| `scripts/familia_cli.py` | engine behind ./familia: subcommand names, help, man page, completion (run as familia help / familia completion) |
| `scripts/with-host-lock` | wrapper: flock ~/.local/state/familia/big.lock around one live/big job per host |
| `scripts/dogfood/dispatch.py` | dogfood: real hermes single/graph + Harness² propose (#110); `--smoke` = render-only/dry-run (via loop.sh) |
| `scripts/dogfood/loop.sh` | dogfood fix loop driver, run by the operator on a dev node, not an end-user task |
| `scripts/dogfood/pytest_vs_baseline.sh` | dogfood loop internals: compares a candidate fix's pytest results to the baseline |
| `scripts/terminal_rsi.py` | Terminal-RSI self-improvement round for a harness target (#88); proposals only, review with scripts/harness2.py |
| `scripts/self_improve_attach.py` | shared Harness² / Terminal-RSI attach hook called by hermes.sh and start_graph.py; not a standalone menu action |
| `scripts/perf/spec_bench.py` | draft/n-gram speculative decoding bench, lossless check, one host (#91); see [specdec-draft.md](specdec-draft.md) |
| `scripts/specdec_seatbelts.py` | Race draft-simple admission (thread budget, missing GGUF); hooked from start/serve/harness2 |
| `scripts/launch_matrix.py` | dev launch matrix: every engine x local model through bench_guard, classifies launch failures vs crashes |
| `scripts/launch_status.py` | library + CLI for launch status protocol v1 and fleet memory admission budget; called by launchers |
| `scripts/measure_prompt.py` | dev measurement of fixed-prompt size for hermes / Harness2 (#89, #85) |
| `scripts/perf/bench_capped.sh` | perf helper: one capped llama-bench run, called by sweep drivers |
| `scripts/perf/bonsai_check.sh` | perf/dev check for Ternary-Bonsai-2 models (#93); needs the PrismML llama.cpp fork |
| `scripts/perf/centos_sweep_driver.sh` | operator's unattended sweep driver for one dev host, not an end-user task |
| `scripts/perf/harness_driver.sh` | perf comparison of plain llama.cpp vs hermes vs Harness2 on one server |
| `scripts/perf/validate_layer_stream.sh` | dev validation of layer streaming vs plan_placement predictions (#90) |
| `scripts/plan_placement.py` | dev predictor ranking placements from measured links (#90); not yet user-facing |
| `scripts/probe_links.py` | dev link probe that feeds plan_placement.py (#90); not yet user-facing |
| `scripts/rerun_all.sh` | operator rerun of results invalidated by the memcg cap bug (#95); one-off |
| `scripts/tune/centos-memory.sh` | root-only OS memory-killer tuning, run once by the operator with sudo; not a menu action |
| `scripts/tune/linux-memory.sh` | root-only OS memory-killer tuning, run once by the operator with sudo; not a menu action |
| `scripts/watchdog/display-watchdog.sh` | root watchdog run by a system timer, never interactively |
| `scripts/watchdog/install-kill-watch.sh` | operator installer for the kill-watch user unit |
| `scripts/watchdog/kill-watch.sh` | long-running journal follower started by its systemd user unit |
| `scripts/watchdog/mem-snapshot.sh` | helper called by kill-watch.sh |
| `scripts/dogfood/install-loop-unit.sh` | operator installer for the dogfood loop systemd user unit (#112) |
| `build-automation.sh` | Legacy llama.cpp v0.7.0 patch/build helper (not menu) | — | — |
| `install/deps.sh` | Unified OS-deps dispatcher (safe-mode bootstrap; [safe-mode-bootstrap.md](safe-mode-bootstrap.md)) | — | — |
| `install/linux/deps.sh` | Linux/macOS OS-deps helper (apt/dnf/pacman/zypper/brew); called via `install/deps.sh` | — | — |
| `install/termux/deps.sh` | Termux OS-deps helper (`getconf`, pytest, …) | — | — |
| `install/freebsd/deps.sh` | FreeBSD OS-deps helper (opt-in `pkg install`) | — | — |
| `install/windows/deps.ps1` | Windows deps check + winget/choco hints | — | `install\windows\deps.ps1` |
| `scripts/build_appimage.sh` | Operator AppImage packaging (not menu) | — | — |
| `scripts/perf/box_multi_size_smoke.py` | Perf/dev multi-size smoke (not menu) | — | — |
| `scripts/familia_home.sh` | Charm/gum front door (`./familia`); legacy catalog is fallback only |
| `scripts/proto_chat.sh` | protomodel REPL from gum home "Talk to the protomodel" |
| `scripts/find_models.sh` | guided model fetch from gum home "Find more models" |
| `scripts/search_x.sh` | X/Twitter search via Agent-Reach from gum home |
| `scripts/windows/familia-home.ps1` | Windows mirror of familia_home.sh (started by familia.cmd) |
| `scripts/start_graph.py` | graph dry-run helper; hosts.start-preview twin retired — use hosts.start / start.sh |

