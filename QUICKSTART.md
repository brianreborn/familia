# familia quick start

The shortest path from nothing to a running, validated setup. Read [README.md](README.md) first for what familia is. Day-to-day administration is in [MANUAL.md](MANUAL.md). This page only links to details; it doesn't repeat them.

Everything below runs from the root of a familia checkout unless it says otherwise.

**The easy way:** run `./familia` (on Windows, `familia.cmd`). It opens a menu grouped by task, and every item shows the exact command it runs, so you pick up the commands below as you go. `./familia-menu.sh --list` prints every item ([docs/commands.md](docs/commands.md) has the same list as a table), and every item is also a command: `./familia help` lists them, e.g. `./familia skills list` or `./familia --dry-run model params coder` (prints the command, runs nothing). Type `/` and a word at any prompt to search every group (`n`/`N` next/previous), or run `./familia search WORD`. Without a terminal it prints the list and exits instead of waiting.

**Prefer a window?** Run `./familia panel` (Windows: `python scripts\panel.py`). It opens a settings page in your browser that works with a mouse, a keyboard alone, a single switch or a screen reader: skills, licenses, hermes mode, Harness2, model launch parameters and launcher settings. You see every change before it is saved, and you can undo it. See [docs/panel.md](docs/panel.md).


## What you actually need

Do these in order. Skipping a step is the usual reason start fails on a new machine.

1. **Install / sync pins** — from a checkout: `./familia sync` (or `python3 scripts/sync_pins.py`). Or use an installer (table below).
2. **Accept licenses** — `python3 scripts/licenses.py review` (or `--yes` / `INSTALL_ACK=yes` for unattended). Nothing starts until this is done.
3. **Measure THIS host into `graph.yaml`** — `python3 scripts/host_measure.py --name NAME --kind desktop|laptop|phone|vm`. The host must appear under `hosts:` with `measured: true`. The OS hostname is recorded under `local_names` so `./start.sh` finds the host even when the graph key differs (e.g. `box` vs `grok-bot-vm-…`). A successful measure also writes a machine-local pin to `~/.local/state/familia/hostname` (Windows: `%LOCALAPPDATA%\familia\hostname`) so menus and start auto-select that graph host without retyping; override with `FAMILIA_HOST` / `--host`, show with `python3 scripts/hostname_pin.py get`. **`curl …/install.sh | sh` alone does not measure the host.** The graph-node installer (`install/linux/install.sh`) does.
4. **Place or select a node/model for this host** — an active `nodes.*` entry whose `host` is the name you measured, pointing at a GGUF that exists on disk. The graph never invents a default model. If the model card has several sampling modes, set `card_set` (and `override_reasons.card_set`) on the node, or `python3 scripts/add_model.py … --card-set LABEL --apply-card-defaults`.
5. **Validate** — `python3 scripts/validate_graph.py --no-files`, then `python3 scripts/validate_graph.py` once the GGUF files are present.
6. **Start / bench** — `./start.sh` (or `./start.sh --host NAME`), or a perf script under `scripts/perf/` once a runtime binary and model exist.

If start says the host is not declared, run step 3. If it says a model file is missing, fetch or copy the GGUF to the path in `models.*.gguf` (see `python3 scripts/add_model.py --fetch … --accept-licenses`).

## 1. Install

Pick one. All of them are per-user (no root or admin).

| What you want | Linux / macOS / Termux | Windows (PowerShell) |
|---|---|---|
| The full stack: familia plus the pinned sub-projects, then the router starts | `curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install.sh \| sh` | not available; use the next row |
| A graph node: familia, a checksum-verified llama.cpp CPU build, this host measured into `graph.yaml` | `curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install/linux/install.sh \| sh` (Termux: `install/termux/install.sh`) | `powershell -ExecutionPolicy Bypass -File install\windows\install.ps1` (or double-click `install\windows\install.bat`) |

- The full-stack installer clones into `~/familia` (`INSTALL_PREFIX` changes that), runs `scripts/configure.sh`, and starts `./start.sh` (`INSTALL_NO_START=1` skips that). It asks you to type `yes` once to acknowledge the voluntary contribution notice; `INSTALL_ACK=yes` answers it for unattended installs. Paying is never required.
- Every installer also puts `familia` on your PATH: a 2-line shim in `~/.local/bin` (Windows: `%LOCALAPPDATA%\Programs\familia\bin` + your user PATH), with the code left where it is. If `~/.local/bin` isn't on your PATH it prints the one line to add, or run `familia path --add`. `--no-path` skips it; from a checkout, `sh scripts/install-cli.sh --dry-run` previews it. Details: [docs/install.md](docs/install.md#familia-on-your-path).
- The graph-node installers, their flags (`--dry-run`, `--uninstall`, `--name`, ...) and install locations are in [docs/install.md](docs/install.md). Windows details: [docs/windows.md](docs/windows.md).

Already have a checkout? Update familia and bring every pinned sub-project to its pin, together:

```sh
./familia update          # git pull --ff-only, then sync; add --dry-run to only look
./familia sync --dry-run  # what is behind pins.txt and would move
./familia sync --branch feat/llama.cpp-0.7.0  # switch to and track the branch, then sync its pins
```

The branch form fetches `origin/BRANCH`, switches this checkout to that branch (creating a local tracking branch if needed), fast-forwards only, and syncs all projects to its `pins.txt`. Later updates and installer runs stay on that tracked branch; use `--branch main` when you explicitly want to switch back. Use `--dry-run` to preview. On Windows, use `python scripts\sync_pins.py --branch feat/llama.cpp-0.7.0`. You rarely need the default sync by hand: the installers, `configure.sh`, `start.sh`, `serve.sh`, `with-fleet.sh`, the panel and the tests all sync first, and after `configure.sh` a `git pull` of familia syncs too. Adding or fetching a model does not.

### Licenses come first

Installers, `start.sh`, `with-fleet.sh`, `start.bat` and the menu's start and fetch items all show the license review before they do anything: every license your models, skills, engines and pinned parts bring in, with unknown or restrictive ones at the top. Type `yes` to accept. You are asked again only if something changes. For unattended runs use `--yes`, which still prints the summary, and add `--accept-unknown` if some licenses are unknown. Details: [docs/licenses.md](docs/licenses.md).

```sh
python3 scripts/licenses.py review
```

## 2. Pick skills

Skills give a small local model written instructions for specific jobs. In the menu, choose **Skills**, then **Bundled skills**, and switch them on or off; each one shows its license and status. A `license-blocked` skill can't be enabled, and pentest roles never get skills that add tools. Bundled skills live in green-zkillz (inside green-agentz). Details: [docs/skills.md](docs/skills.md).

```sh
scripts/skills.py list
scripts/skills.py enable green-probe --dry-run
```

## 3. Check the graph

`graph.yaml` declares every host, model, node and agent. Nothing starts unless it validates.

```sh
python3 scripts/validate_graph.py --no-files   # schema and placement rules only
python3 scripts/validate_graph.py              # also reads GGUF headers, model-database entries and the RAM budget
python3 scripts/validate_graph.py --args coder # the exact llama-server command line for node "coder"
```

On Windows use `python` instead of `python3` and set `$env:PYTHONUTF8 = '1'` first. Warnings such as `no registry record` are informational. What the checks mean: [docs/graph-types.md](docs/graph-types.md).

## 4. Start something

| Goal | Command |
|---|---|
| Active local graph topology (POSIX) | `./start.sh` (or `./start.sh --host miryam`); current gateway aliases are listed at `http://127.0.0.1:9931/v1/models` |
| Legacy standalone bootstrap UI/router | `./start.sh --bootstrap`, then open http://127.0.0.1:9931/?model=chat and paste its API key |
| One graph node's llama-server (Linux) | `sh scripts/serve.sh coder` |
| One node on Windows | `$env:FAMILIA_MODEL = 'your-model.gguf'; .\scripts\windows\start.bat` |
| hermes-agent against the graph | `scripts/hermes.sh` |

`./start.sh --host miryam` defaults to `DETACH_MODE=screen-attached`: visible `familia-server` screen session with 10,000 lines of scrollback. Use `Ctrl-A`, then `D` to detach and `screen -r familia-server` to resume. Other modes (`screen`, `tmux`, `nohup`, `foreground`) are opt-in. See [MANUAL.md](MANUAL.md#backgrounding-and-detaching).

The FreeBSD graph host `angel` is **measured** (`hosts.angel.measured: true`, ~24 GiB RAM) and **`angel-coder` is active** (Nanbeige4.3-33B Q4_K_M; `angel-chat` stays `planned` — do not co-start). `./start.sh --dry-run --host angel` reports this without starting or contacting anything. FreeBSD currently uses a source build only—install no packages and do not run `familia install`. Run the pinned llama.cpp build/version test from `code-bootstraps-llama.cpp` with `BUILD_DIR=build-freebsd GPU=off scripts/build-linux.sh`; graph serving requires measured host facts and explicit active-node placement. Before flipping `angel-coder` / `angel-chat` to `active`, measure SSD swap (≈24 GiB target) and create `~/.cache/familia/spill/angel-*` — see `docs/vvram-ssd/README.md` and install-notes `vvram-ssd/LAYER.md`. Do not co-activate both on 24 GiB.

### Always run hermes through the harness

Run `scripts/hermes.sh`, not the stock `hermes` command. The stock config in `~/.hermes` has compression off and points at models whose context is far smaller than what hermes sends, so every long turn fails with HTTP 400 (the [#19](https://github.com/brianreborn/familia/issues/19) failure, seen again on 2026-10-18). The harness renders its own config under `~/.cache/familia/hermes-<agent>` with `context_length` equal to the node's per-slot context (65,536 on `coder`) and compression on. It only reads `~/.hermes`.

It has two modes:

- **Graph mode**, the default and the same behaviour as before. hermes uses its agent's
  `main` and `auxiliary` aliases from `graph.yaml`. The escalation proxy comes on by itself
  only when the main node declares `escalates_to` (none does today).
- **Single-model mode** (limp / last resort), `--model NODE`. Prefer the multi-node graph; hermes uses that one node, with its own
  `~/.cache/familia/hermes-<agent>@<node>`, `context_length` set to the node's per-slot
  context, compression on, auxiliary tasks on the same node, and no aliases or proxy. Nodes
  under the agent's `min_ctx` (hermes needs 64,000 tokens) are refused, with a list of the
  nodes that fit.

```sh
scripts/hermes.sh --render-only           # graph mode: write the config, start nothing
scripts/hermes.sh                         # validate, start the coder node if needed, run hermes
scripts/hermes.sh --selftest-compaction   # check that compaction keeps facts on this node
scripts/hermes.sh --escalate -- ARGS      # with the light-to-heavy escalation proxy (docs/escalation.md)
scripts/hermes.sh --graph-mode            # graph mode, said explicitly (same as no flag; --graph FILE only picks the file)
scripts/hermes.sh --model coder           # single-model mode on node coder
scripts/hermes.sh --model coder --selftest-compaction
```

Skills you enabled with `scripts/skills.py` are linked into the HERMES_HOME in both modes.
`--escalate`, `--light` and `--no-swap-back` work in graph mode only; with `--model` they exit with
an error. `--no-escalate` turns the automatic proxy off. Self-improving harnesses (Harness²)
are a separate, optional layer that hermes picks up when the graph enables it:
[docs/harness2.md](docs/harness2.md).

The harness resolves hermes-agent automatically: Linux snap (`/snap/bin/hermes-agent`) when present; FreeBSD ports (`/usr/local/bin/hermes-agent`, packages under `/usr/local/lib/hermes-agent`, not site-packages); otherwise `PATH`. Override with `HERMES_BIN` / `HERMES_PY` / `HERMES_SP`. On angel (FreeBSD): `pkg install hermes-agent` then `scripts/hermes.sh --model angel-coder --render-only` (host-scoped; no box GGUFs). Launch still needs a node whose per-slot ctx ≥ agent `min_ctx` (64K hermes-agent floor) — `angel-coder` is 32K today; see docs/vvram-ssd/ANGEL-OPERATOR.md.

## 5. Add a model

```sh
./scripts/add-model.sh --dry-run ~/models/SomeOrg--Some-Model-GGUF   # see what it infers; writes nothing
./scripts/add-model.sh ~/models/SomeOrg--Some-Model-GGUF             # a Hugging Face snapshot directory
./scripts/add-model.sh path/to/model.gguf                            # a lone GGUF; the role is inferred
./scripts/add-model.sh --fetch ORG/NAME@REV --quant Q4_K_M           # download the repo's small files and one GGUF first
./scripts/add-model.sh --fetch ORG/NAME@REV --dry-run                # plan only: each file, size, sha256, license; no network writes
./scripts/add-model.sh --fetch ORG/NAME@REV --damp-run               # small files + DB entry, weights skipped ("weights: absent (damp)")
./scripts/add-model.sh --help                                        # every flag
```

- Run modes, the same in `add-model.sh --fetch`, `scripts/hf_fetch.py` and `scripts/model_db.py backfill` (code-bootstraps `scripts/fetch-models.sh` has them too):
  - `--dry-run` downloads and writes nothing. It prints the plan: every file in the repo with its size and sha, and whether it is present, would be fetched, or skipped as a weight or as too large. It also prints the license.
  - `--damp-run` fetches only missing small files (under 50 MB; change with `--max-file-mb`). Weights are skipped, but their size and LFS sha256 are recorded. The DB entry says `weights: absent (damp)`, and `validate_graph.py` refuses to run such a node until a full run fetches it. `scripts/model_db.py damp REPO...` does this for many repos.
  - With neither flag you get the full run, the default.
- Licenses come before anything runs. Before a full fetch downloads weights, the license of what you picked is printed: id, link, the license file and obligations quoted from the card with file and line. You must accept it with `--accept-licenses` (alias `--yes`) or answer yes at the prompt. With no terminal and no flag, nothing is downloaded (exit 2). `serve.sh` and `hermes_harness.py` likewise run `scripts/licenses.py gate --graph` before starting a server. `--dry-run` only prints. A damp run prints the license and needs no acceptance, since no weights are fetched. Unknown licenses are shown as UNKNOWN, never guessed.

- Give it a whole Hugging Face snapshot directory when you can: the model card, `config.json`, tokenizer and chat-template files are what the launch settings come from. Auxiliary files (`mmproj-*`, draft and MTP GGUFs) in the directory are picked up automatically, or name them with `--aux KIND=PATH`.
- `--role` (alias `--type`) is optional. The role is inferred from the card, `config.json`, GGUF metadata, the filename and the directory, and the evidence is printed. If it's still ambiguous it asks, or exits 2 when there is no terminal.
- The old `./scripts/add-model.sh ROLE FILE.gguf` form still works.
- It writes the code-bootstraps-llama.cpp model manifest and preset. To serve the model from the graph, add `models:` and `nodes:` entries to `graph.yaml` and validate again.

Model database rules (full pinned HF repo, card settings as launch defaults): [docs/model-database.md](docs/model-database.md).

## 6. Test

```sh
sh scripts/run-tests.sh          # installs pytest into .cache/pylib once; no sudo
```

PyYAML is still needed for the graph checks (`python3 -m pip install --user pyyaml`). One failure is known: `test_overcommit_is_hard_error`.

Expected results per platform, the bash smoke tests, and how to report back: [TESTING.md](TESTING.md).

## Next

- `./familia-monitor` watches every host over SSH and flags any familia process that dies ([docs/monitoring.md](docs/monitoring.md)).
- [MANUAL.md](MANUAL.md): settings, detaching, models, escalation, RAM safety, Windows.
- [docs/known-issues.md](docs/known-issues.md): current problems and workarounds.
