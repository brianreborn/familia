# Windows (qodesh) startup (#17)

Status: scripts shipped, **not yet run end to end on qodesh**. The one-click installer is `install\windows\install.bat` / `install\windows\install.ps1` (see docs/install.md); there is no `configure.ps1`.

## Requirements
- Windows 10 x64. **No AVX required**: the official ggml-org `llama-*-bin-win-cpu-x64.zip` selects its CPU
  backend at runtime and ran on qodesh's Athlon II X2 B24 (SSE only) on 2026-10-09.
- Unzip the release into `runtime\` at the repo root (or set `FAMILIA_RUNTIME`).
- Models: `E:\temp\familia\models` when `E:\temp` exists (C: has ~4.6 GiB free), else `%USERPROFILE%\familia\models`,
  or set `FAMILIA_MODELS`.

## Run once
```
set FAMILIA_MODEL=your-model.gguf
scripts\windows\start.bat
```
Binds 127.0.0.1:9941 by default; log in `<models>\..\logs\`. Variables are listed at the top of `start.bat`;
keep them equal to the node in `graph.yaml`.

## Autostart at logon (opt-in)
```
powershell -ExecutionPolicy Bypass -File scripts\windows\install-task.ps1 -Install -Model your-model.gguf
powershell -ExecutionPolicy Bypass -File scripts\windows\install-task.ps1 -Uninstall
```
Without `-Install` it only prints how to opt in. The task runs as you, only while logged on, without elevation,
60 s after logon, restarting up to 3 times. Add `-WhatIf` to preview.

## Graph
`hosts.qodesh.windows` records `startup`, `start_script`, `task_name`, `autostart` (must stay `false` until you opt in)
and `avx_required: false`. The validator checks these.
