# FAMILIA Administration and Usage Manual

Welcome to the definitive guide for setting up and managing a FAMILIA topology. This manual focuses on practical installation, daily administration, and usage.

## 1. Installation

Installation takes only two steps and applies identically across Linux, macOS, and Termux (Android).

```sh
curl -fsSL https://raw.githubusercontent.com/brianreborn/feeldznutts/main/install.sh | sh
```
For Windows PowerShell:
```powershell
irm https://raw.githubusercontent.com/brianreborn/feeldznutts/main/install.ps1 | iex
```

**Note**: The installer will prompt for acknowledgment of the Light-ware License. Type `yes` to proceed. If running in an automated environment, set `INSTALL_ACK=yes` before executing the script.

## 2. Configuration & Administration

### The Visual Topology Editor

FAMILIA allows you to configure your node graph visually or via natural language commands.
- Run `sh scripts/configure.sh` (or `scripts\configure.ps1` on Windows) to open the interactive configuration panel.
- On Linux/Termux environments, this will launch a visual `whiptail` menu where you can set up a small local network or expand to federated topologies across multiple hosts.

### Environmental Overrides
Settings are persistently stored in `.cache/panel.env`. You can always override these values dynamically by setting environment variables before launching.

Examples:
- `PORT=8080 ./start.sh`
- `PROFILE=lowram ./start.sh`

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
FAMILIA offers robust backgrounding natively. Set the `DETACH_MODE` via the configuration panel to choose between:
- `foreground` (default)
- `nohup` (outputs to `.cache/server.log`)
- `tmux` or `screen` (launches in a detached session)

Android/Termux users: `termux-wake-lock` is automatically held to prevent the OS from killing the background daemon during inference.

## 4. Alternate Engines and Roles

You can register alternative model runtimes (like Ollama or experimental `llama.cpp` forks).
For instance, the `chat` route can be configured to use a specialized discrete residual diffusion model engine (DReX-DLM). 

To do so:
1. Open the configuration UI.
2. Select the `ENGINE_CHAT` setting.
3. Enter the engine identifier (e.g., `nace-ai__edlm`).
FAMILIA will automatically fetch, compile, and isolate the specified engine.
