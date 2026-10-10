# FAMILIA Administration and Usage Manual

Welcome to the definitive guide for setting up and managing a FAMILIA topology. This manual focuses on practical installation, daily administration, and usage.

## 1. Installation

Installation takes two steps. Linux is tested; Termux (Android) is partly tested; macOS is expected to work but untested.

```sh
curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install.sh | sh
```
*Windows: one-click `install\windows\install.bat` (wraps `install\windows\install.ps1`), plus `scripts\windows\start.bat` and an opt-in logon task (`scripts\windows\install-task.ps1`); see docs/windows.md and docs/install.md. Windows has no `configure.ps1`; the installer does that step itself.*

**Note**: The installer will prompt for acknowledgment of the Light-ware License. Type `yes` (or `y`) to proceed. If running in an automated environment, set `INSTALL_ACK=yes` before executing the script.

## 2. Configuration & Administration

### Settings

- `sh scripts/configure.sh` syncs the sub-projects in `pins.txt` to their pinned revisions (non-interactive).
- `sh scripts/configure.sh -i` adds interactive prompts in the terminal. There is no visual (whiptail) editor and no natural-language configuration yet; both are planned (see DESIGN.md and `docs/configuration-graph.md`).
- `python3 scripts/panel.py` serves a browser settings panel at http://127.0.0.1:9932.

### Where settings live
Saved settings are in `code-bootstraps-llama.cpp/.cache/panel.env` (the sub-project's panel file; `configure.sh` reads it from there). Environment variables always override them:

- `PORT=8080 ./start.sh`
- `PROFILE=lowram ./start.sh`

### Model/agent graph
Model nodes, runtimes and agents are declared in `graph.yaml` and checked with `python3 scripts/validate_graph.py`. The hermes-agent harness (`scripts/hermes.sh`) uses it. `start.sh` does not read the graph yet. See `docs/configuration-graph.md` and `docs/ram-safety.md`.

## 3. Usage and Operations

To start the system after configuration:
```sh
./start.sh
```

### Accessing the Web UI
By default, the server runs on port `9931`.
Navigate to: `http://127.0.0.1:9931/?model=chat`
On first load, you must provide the API key printed in the server terminal logs.

### Backgrounding and Detaching
`start.sh` reads `DETACH_MODE` from the environment (it is not a panel setting):

```sh
DETACH_MODE=nohup ./start.sh     # foreground (default) | nohup | tmux | screen
```

- `nohup` logs to `.cache/server.log`.
- `tmux` / `screen` start a detached session named `familia-server`.
- On Termux, if `DETACH_MODE` is left at `foreground`, `start.sh` picks tmux, then screen, then nohup, and takes `termux-wake-lock` when it is installed.

## 4. Alternate Engines and Roles

You can register alternative model runtimes (like Ollama or experimental `llama.cpp` forks).
For instance, the `chat` route can be configured to use a specialized discrete residual diffusion model engine (DReX-DLM). 

Set `ENGINE_CHAT` (e.g. `nace-ai__edlm`) in the settings panel or environment. Today `configure.sh` only **clones** the pinned engine source (`llama-server__nace-ai__edlm` in `pins.txt`); building and isolating it is not automated yet.

Official llama.cpp release builds can already run side by side via the `runtimes:` section of `graph.yaml` (b11374 for `coder`, b11539 for `embed`).
