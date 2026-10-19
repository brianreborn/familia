# familia quick start

The shortest path from nothing to a running, validated setup. Read [README.md](README.md) first for what familia is. Day-to-day administration is in [MANUAL.md](MANUAL.md). This page only links to details; it doesn't repeat them.

Everything below runs from the root of a familia checkout unless it says otherwise.

## 1. Install

Pick one. All of them are per-user (no root or admin).

| What you want | Linux / macOS / Termux | Windows (PowerShell) |
|---|---|---|
| The full stack: familia plus the pinned sub-projects, then the router starts | `curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install.sh \| sh` | not available; use the next row |
| A graph node: familia, a checksum-verified llama.cpp CPU build, this host measured into `graph.yaml` | `curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install/linux/install.sh \| sh` (Termux: `install/termux/install.sh`) | `powershell -ExecutionPolicy Bypass -File install\windows\install.ps1` (or double-click `install\windows\install.bat`) |

- The full-stack installer clones into `~/familia` (`INSTALL_PREFIX` changes that), runs `scripts/configure.sh`, and starts `./start.sh` (`INSTALL_NO_START=1` skips that). It asks you to type `yes` once to acknowledge the voluntary contribution notice; `INSTALL_ACK=yes` answers it for unattended installs. Paying is never required.
- The graph-node installers, their flags (`--dry-run`, `--uninstall`, `--name`, ...) and install locations are in [docs/install.md](docs/install.md). Windows details: [docs/windows.md](docs/windows.md).

Already have a checkout? Sync the pinned sub-projects:

```sh
sh scripts/configure.sh
```

On Windows, run the same through Git Bash (there is no `configure.ps1`):

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/configure.sh
```

## 2. Check the graph

`graph.yaml` declares every host, model, node and agent. Nothing starts unless it validates.

```sh
python3 scripts/validate_graph.py --no-files   # schema and placement rules only
python3 scripts/validate_graph.py              # also reads GGUF headers, model-database entries and the RAM budget
python3 scripts/validate_graph.py --args coder # the exact llama-server command line for node "coder"
```

On Windows use `python` instead of `python3` and set `$env:PYTHONUTF8 = '1'` first. Warnings such as `no registry record` are informational. What the checks mean: [docs/graph-types.md](docs/graph-types.md).

## 3. Start something

| Goal | Command |
|---|---|
| The web UI and router (code-bootstraps-llama.cpp) | `./start.sh`, then open http://127.0.0.1:9931/?model=chat and paste the API key printed in the terminal |
| One graph node's llama-server (Linux) | `sh scripts/serve.sh coder` |
| One node on Windows | `$env:FAMILIA_MODEL = 'your-model.gguf'; .\scripts\windows\start.bat` |
| hermes-agent against the graph | `scripts/hermes.sh` |

`DETACH_MODE=nohup|tmux|screen ./start.sh` keeps the router running after the terminal closes; see [MANUAL.md](MANUAL.md#backgrounding-and-detaching).

### Always run hermes through the harness

Run `scripts/hermes.sh`, not the stock `hermes` command. The stock config in `~/.hermes` has compression off and points at models whose context is far smaller than what hermes sends, so every long turn fails with HTTP 400 (the [#19](https://github.com/brianreborn/familia/issues/19) failure, seen again on 2026-10-18). The harness renders its own config under `~/.cache/familia/hermes-<agent>` with `context_length` equal to the node's per-slot context (65,536 on `coder`) and compression on. It only reads `~/.hermes`.

```sh
scripts/hermes.sh --render-only           # write the config, start nothing
scripts/hermes.sh                         # validate, start the coder node if needed, run hermes
scripts/hermes.sh --selftest-compaction   # check that compaction keeps facts on this node
scripts/hermes.sh --escalate -- ARGS      # with the light-to-heavy escalation proxy (docs/escalation.md)
```

The harness expects hermes-agent at `/snap/bin/hermes-agent`; set `HERMES_BIN` if yours is elsewhere.

## 4. Add a model

```sh
./scripts/add-model.sh --dry-run ~/models/SomeOrg--Some-Model-GGUF   # see what it infers; writes nothing
./scripts/add-model.sh ~/models/SomeOrg--Some-Model-GGUF             # a Hugging Face snapshot directory
./scripts/add-model.sh path/to/model.gguf                            # a lone GGUF; the role is inferred
./scripts/add-model.sh --fetch ORG/NAME@REV --quant Q4_K_M           # download the repo's small files and one GGUF first
./scripts/add-model.sh --help                                        # every flag
```

- Give it a whole Hugging Face snapshot directory when you can: the model card, `config.json`, tokenizer and chat-template files are what the launch settings come from. Auxiliary files (`mmproj-*`, draft and MTP GGUFs) in the directory are picked up automatically, or name them with `--aux KIND=PATH`.
- `--role` (alias `--type`) is optional. The role is inferred from the card, `config.json`, GGUF metadata, the filename and the directory, and the evidence is printed. If it's still ambiguous it asks, or exits 2 when there is no terminal.
- The old `./scripts/add-model.sh ROLE FILE.gguf` form still works.
- It writes the code-bootstraps-llama.cpp model manifest and preset. To serve the model from the graph, add `models:` and `nodes:` entries to `graph.yaml` and validate again.

Model database rules (full pinned HF repo, card settings as launch defaults): [docs/model-database.md](docs/model-database.md).

## 5. Test

```sh
python3 -m pip install --user pyyaml pytest
python3 -m pytest -q tests
```

Expected results per platform, the bash smoke tests, and how to report back: [TESTING.md](TESTING.md).

## Next

- `./familia-monitor` watches every host over SSH and flags any familia process that dies ([docs/monitoring.md](docs/monitoring.md)).
- [MANUAL.md](MANUAL.md): settings, detaching, models, escalation, RAM safety, Windows.
- [docs/known-issues.md](docs/known-issues.md): current problems and workarounds.
