# familia administration and usage manual

How to run and look after a familia setup day to day. Install and first start are in [QUICKSTART.md](QUICKSTART.md); this manual picks up from there. Commands run from the root of the checkout. On Windows, use `python` for `python3` and run `.sh` scripts with Git Bash (`& 'C:\Program Files\Git\bin\bash.exe' scripts/NAME.sh`); PowerShell 5.1 has no `&&`, so run commands one per line.

## The menu

`./familia` (Windows: `familia.cmd`) opens the menu. Items are grouped by task, and each one shows the command it runs. One table, `scripts/menu-items.txt`, drives the menu on both platforms, so a new item goes in that file (an empty Linux column means Windows only). Every user-facing script must have an item; scripts that are only called by other scripts or are developer-only go in `scripts/menu-internal.txt` with a reason, and `tests/test_menu.py` fails on a script in neither. Advanced commands (model database, launch arguments, escalation, benchmark records, uninstall, FreeBSD) are in the three Advanced groups. [docs/commands.md](docs/commands.md) lists everything; update it when you add an item. `./familia-menu.sh --list` prints every item, `--run KEY [ARG...]` runs one, and `--dry-run` prints the command instead of running it. Every item is also a subcommand, `./familia COMMAND [VALUE...] [ARG...]`, with natural names from `scripts/cli-commands.txt` plus automatic ones for every row; `./familia help [COMMAND]`, `man ./man/familia.1`, and [docs/commands.md](docs/commands.md#command-line) explain them. Regenerate the man page after adding a row: `python3 scripts/familia_cli.py man --write`. Items that start or fetch something run the license review first (`scripts/licenses.py gate`, [docs/licenses.md](docs/licenses.md)). Items whose command hasn't landed yet are marked "not available yet". To find an item, type `/word` at any prompt (`?word` searches backward, `n`/`N` move between matches, `/` alone repeats); a picked result runs exactly like the item in its group. `./familia search WORD [--run N]` (Windows: `familia.cmd -Search WORD [-Run N]`) does the same without the menu. See [docs/commands.md](docs/commands.md#search). Without a terminal the menu prints its items and exits 2. Use `--pipe` to feed choices from a script.


`familia` on your PATH: the installers write a 2-line shim `~/.local/bin/familia` (Termux `$PREFIX/bin`, Windows `%LOCALAPPDATA%\Programs\familia\bin\familia.cmd` + user PATH) that runs the checkout's `familia`; nothing is copied. `familia install-cli [--dry-run] [--prefix DIR]` does it by hand, `familia path --add`/`--remove` manage one marked block in `~/.profile` (never touched otherwise), `familia install-cli status` shows it, and `familia uninstall-cli` removes exactly the files recorded in `~/.local/state/familia/installed.txt`. See [docs/install.md](docs/install.md#familia-on-your-path).

## 1. Settings

- `sh scripts/configure.sh` checks out every sub-project in [`pins.txt`](pins.txt) at its pinned revision. It is non-interactive and safe to re-run.
- `sh scripts/configure.sh -i` also asks for settings in the terminal.
- `./familia panel` (or `python3 scripts/panel.py`) starts the settings panel at http://127.0.0.1:9932 and opens it in your browser. It is the code-bootstraps-llama.cpp panel with familia's pages added (skills, licenses, hermes, Harness2, models); it needs `configure.sh` to have run first. See [docs/panel.md](docs/panel.md).

Saved settings live in `code-bootstraps-llama.cpp/.cache/panel.env`. An environment variable always overrides a saved setting:

```sh
PORT=8080 ./start.sh
PROFILE=lowram ./start.sh        # lowram | moderate | default
```

Other common variables: `CTX`, `CODER_CTX`, `MODELS_MAX`, `TOOLS`, `CACHE_RAM`. The full list is in the [code-bootstraps-llama.cpp README](https://github.com/brianreborn/code-bootstraps-llama.cpp#readme). The prompt cache size follows the profile (lowram 768, moderate 1024, default 2048 MiB, never more than a quarter of free RAM) unless `CACHE_RAM` sets it.

There is no visual graph editor and no natural-language configuration (see [Future ideas](#future-ideas)).

## 2. Starting and stopping

### The router and web UI

```sh
./start.sh
```

It serves http://127.0.0.1:9931/?model=chat. On first load, paste the API key printed in the terminal. `start.sh` does not read `graph.yaml` yet.

### Backgrounding and detaching

`start.sh` reads `DETACH_MODE` from the environment (it is not a panel setting):

```sh
DETACH_MODE=nohup ./start.sh     # foreground (default) | nohup | tmux | screen
```

- `nohup` logs to `.cache/server.log`.
- `tmux` and `screen` start a detached session named `familia-server`.
- On Termux, if `DETACH_MODE` is left at `foreground`, `start.sh` picks tmux, then screen, then nohup, and takes `termux-wake-lock` when it is installed.

### One graph node

```sh
sh scripts/serve.sh coder                       # Linux: llama-server with the node's exact graph arguments
python3 scripts/validate_graph.py --args coder  # print those arguments without starting anything
```

- On miryam, `serve.sh` runs the server inside a `systemd-run --user` scope (MemoryHigh 2200M, MemoryMax 2600M, no swap, `oom_score_adj` 800) so memory pressure kills the model and not the desktop. `FAMILIA_MEMCAP=0|1` turns that off or on for any host; `FAMILIA_MEMHIGH` / `FAMILIA_MEMMAX` change the limits.
- When a node has no GPU layers (`-ngl 0`), `serve.sh` and the hermes harness export an empty `GGML_VK_VISIBLE_DEVICES`. Without it a Vulkan build allocates about 1.8 GB of shared memory it never uses, which stalls a memcapped server (LESSONS-LEARNED L-vkshm). Live re-verification is planned ([#40](https://github.com/brianreborn/familia/issues/40)). Windows `serve.ps1` can't set an empty variable, so on Windows use a CPU build for `-ngl 0` nodes.
- On Windows: `$env:FAMILIA_MODEL = 'your-model.gguf'` then `.\scripts\windows\start.bat`. Autostart at logon and the variables are in [docs/windows.md](docs/windows.md).

### Watching the fleet

`./familia-monitor` (live), `--once`, `--json` or `--watch-deaths` probes every host over SSH, read-only, and raises an alert when a server dies or is OOM-killed. See [docs/monitoring.md](docs/monitoring.md).

## 3. The graph

[`graph.yaml`](graph.yaml) declares hosts, runtimes, models, nodes, aliases, agents and pentest roles. Nothing is picked for you: a model runs only when a `models:` entry and a `nodes:` entry say so, and `scripts/validate_graph.py` refuses a graph that doesn't fit the measured host.

```sh
python3 scripts/validate_graph.py              # full check on this host
python3 scripts/validate_graph.py --no-files   # schema and placement only (CI, other hosts)
python3 scripts/validate_graph.py --verify-sha # also hash the GGUFs
```

- Every section and rule: [docs/graph-types.md](docs/graph-types.md). Why the graph works this way: [docs/configuration-graph.md](docs/configuration-graph.md).
- **Default and fallback models.** A node marked `selection: fallback` is a user-selectable alternative, not the default. Today `qodesh-resident` (Qwen3.5-2B, about 0.9 tok/s) is the fallback on qodesh and SmolLM2 stays the default.
- **Per-host copies.** `python3 scripts/generate_graph.py HOST [--set NODE=MODEL_PATH]` writes `generated/graph-HOST.yaml` without touching `graph.yaml`; validate it with `--graph`.

## 4. Models

### Adding a model

`./scripts/add-model.sh` takes a Hugging Face snapshot directory, a lone GGUF, or explicit flags (`--repo`, `--file`, `--card`, `--aux KIND=PATH`, ...), infers the role when you don't give one, and writes the code-bootstraps-llama.cpp manifest and preset. Examples are in [QUICKSTART.md](QUICKSTART.md#5-add-a-model); `--help` lists every flag. After adding, put the model into `graph.yaml` if a graph node should serve it.

Run modes: `--dry-run` prints the plan and changes nothing. `--damp-run` fetches only small files (`--max-file-mb`, default 50) and records the weights' size and sha256 with `weights: absent (damp)`; such a node is not runnable until a full run. The full run is the default. The same flags exist in `scripts/hf_fetch.py`, `scripts/model_db.py backfill`, `scripts/model_db.py damp REPO...` and code-bootstraps `scripts/fetch-models.sh`.

License acceptance: every DB entry carries `license_info` with:
- the exact license id and where it came from
- the license file(s), with path, URL and sha256, and a link
- obligations quoted from the card or license, each with `file:line`

Unknown stays unknown. A full fetch prints this and needs `--accept-licenses`/`--yes` or an interactive yes before it downloads weights. Acceptance is recorded per model and license digest in `.cache/familia/model-license-acceptance.json`, so a changed license is asked again. Launching (`serve.sh`, `hermes_harness.py`) is gated by `scripts/licenses.py gate --graph`. See [docs/licenses.md](docs/licenses.md).

### The model database

Every model in use has an entry in `registry/models/`, built from its full Hugging Face repo pinned to a commit. The model card's recommended settings are the launch defaults, and the validator fails on a node that differs from its card without a written reason. Details and the remaining work: [docs/model-database.md](docs/model-database.md) (#51).

### The measured registry

`registry/records.jsonl` holds measured speed, RAM and correctness per model, host and setting. Look results up before tuning again:

```sh
python3 scripts/registry.py summarize
python3 scripts/registry.py suggest --host miryam --role coder --graph graph.yaml
python3 scripts/registry.py add result.json
```

Tuning uses a coarse binary search: try the ends and the midpoint of a setting with one short run, keep the better half, and only add repetitions or longer inputs when two options are within noise. Records made this way say "coarse binary search" in their notes. See [docs/model-registry.md](docs/model-registry.md).

## 5. Agents

### hermes-agent

Always launch hermes through the harness, `scripts/hermes.sh`. Stock `hermes` uses `~/.hermes`, which has compression off and small-context models, and fails with HTTP 400 on long turns. Commands and what the harness sets: [QUICKSTART.md](QUICKSTART.md#always-run-hermes-through-the-harness).

`hermes.sh` runs in graph mode by default: the agent's aliases from `graph.yaml`, plus the escalation proxy where the main node declares `escalates_to`. `hermes.sh --model NODE` is single-model mode: that one node, its own HERMES_HOME, no router, and nodes under the 64K floor refused.

### Skills

Skills are chosen per agent with `scripts/skills.py`, or with the menu (Skills, then Bundled skills). The choice is saved as `skills: [ids]` under the agent in `graph.yaml`, with comments preserved. The catalog is `skills/catalog.json`, and the bundled skills themselves live in green-zkillz (`green-agentz/skills`). Before a skill is enabled, its license is shown and has to be accepted. `license-blocked` and not-yet-vendored skills are refused with the reason, and the graph check rejects tool-adding skills on pentest roles. `scripts/skills.py paths` prints the folders of the enabled skills. hermes doesn't load them on its own yet. Details: [docs/skills.md](docs/skills.md).

### Self-improving harnesses (optional)

`harnesses:` descriptors name an agent's prompt, guardrails, memory and skills files. `self_improve:` settings point Harness² at them (`mode: "off" | propose | apply`, off in the repo). `scripts/harness2.py` proposes, shows, accepts and reverts changes to those files. It never launches an agent and doesn't need hermes. hermes picks up the accepted version only when the graph enables it for that agent. Pentest agents and models never self-improve. Details: [docs/harness2.md](docs/harness2.md).

```sh
scripts/harness2.py status
scripts/harness2.py propose --target hermes-lab --enable --max-tasks 1 --start-node
scripts/harness2.py show --target hermes-lab ID && scripts/harness2.py accept --target hermes-lab ID
scripts/harness2.py revert --target hermes-lab
```

### Escalating to a heavier model

A light node can name heavier nodes in `escalates_to`. When a session looks stuck (repeated near-identical replies, repeated tool failures, "try harder", a hard task tag, or 10 minutes on one problem), familia suggests the fastest measured target with an ETA. `auto` mode swaps on its own only on the same host or after you have consented once to that cross-host target.

```sh
scripts/hermes.sh --escalate -- ARGS        # hermes behind the escalation proxy
python3 scripts/escalate.py accept           # accept a pending suggestion
python3 scripts/escalate.py consent --node qodesh-smol-cpu --target coder
```

The default mode is `suggest`. The green-roomz router hookup, live swap and reachability probe are planned ([#39](https://github.com/brianreborn/familia/issues/39)). Details: [docs/escalation.md](docs/escalation.md).

## 6. RAM safety

Small hosts keep a large reserve and run one heavy process at a time. The validator fails on a clear overcommit and warns when the reserve or the small-host floor would be broken. miryam also runs earlyoom and zram; a 4 GiB swapfile is planned ([#43](https://github.com/brianreborn/familia/issues/43)). Rules and deployment: [docs/ram-safety.md](docs/ram-safety.md).

## 7. Phones (Termux)

```sh
./android_start.sh phone7          # one phone, target read from graph.yaml
./android_multi_start.sh           # every phone in graph.yaml
./watchdog_android.sh phone7       # restart the node when it stops answering
```

They use key-only SSH and read each phone's address, user and port from `graph.yaml` (or `ANDROID_HOST`, `ANDROID_USER`, `ANDROID_PORT`). They never take passwords or turn off host-key checking. Phone setup for Vulkan: [TESTING.md](TESTING.md#5-phones-vulkan-on-android-termux).

## 8. Pentest roles

Pentest roles (`pentests:` in the graph) are for operator-authorized testing of your own fleet, and are **launch-tested only**: validate → start → healthcheck → stop. Tools are disabled two independent ways for every launch test. The rule, word for word, is in [REQUIREMENTS.md](REQUIREMENTS.md); candidate models are in [docs/pentest-models.md](docs/pentest-models.md).

## 9. Alternate engines

Official llama.cpp release builds run side by side through the `runtimes:` section of `graph.yaml` (b11374 for `coder`; b11539 is load-tested for `embed`, which is deferred in [#38](https://github.com/brianreborn/familia/issues/38)). A node whose GGUF architecture isn't listed for its runtime fails validation.

Experimental forks are pinned as `<executable>__<author>__<branch>` in `pins.txt`. For example, `ENGINE_CHAT=nace-ai__edlm` selects the DReX-DLM diffusion engine for `chat`. Today `configure.sh` only clones that source; building and isolating it is not automated.

## Future ideas

Not planned yet and not tracked in an issue:

- A visual, netgraph-style graph editor and natural-language configuration (DESIGN.md).
- `start.sh` reading `graph.yaml` directly.
