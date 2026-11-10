# Windows (qodesh) startup (#17)

Status: scripts shipped, **not yet run end to end on qodesh**. The one-click installer is `install\windows\install.bat` / `install\windows\install.ps1` (see docs/install.md); there is no `configure.ps1`.

## Requirements
- Windows 10 x64. **No AVX required**: the official ggml-org `llama-*-bin-win-cpu-x64.zip` selects its CPU
  backend at runtime and ran on qodesh's Athlon II X2 B24 (SSE only) on 2026-10-09.
- Installer prefix (override `-Prefix`): `%LOCALAPPDATA%\familia`. The installer puts the llama.cpp
  build in `%LOCALAPPDATA%\familia\runtime` (`$Prefix\runtime`). For a manual unzip without the
  installer, `scripts\windows\start.bat` still defaults `FAMILIA_RUNTIME` to `runtime\` at the repo
  root; after an installer run, set `FAMILIA_RUNTIME` to the prefix runtime dir.
- Models default to `$Prefix\models` (`%LOCALAPPDATA%\familia\models` unless you pass `-Prefix`).
  External models are used only when you pass `-ModelsPath`. Older installs may still have files
  under `E:\temp\familia\models`; that path is not the default. `-AdoptInstall` never records
  an external models dir, and `-Purge` will not remove that folder (delete it manually if you
  no longer want it). After an installer run, set `FAMILIA_MODELS` when using `start.bat` (if
  unset, start.bat still probes `E:\temp` then `%USERPROFILE%\familia\models`, which will
  miss the prefix models dir).
- Uninstall and purge require a `.familia-install` marker under the prefix
  (`install.ps1 -Uninstall` / `-Purge`). For a pre-marker install, run `install.ps1 -AdoptInstall`
  once (add `-ConfirmAdopt` when non-interactive). `-Purge` does not delete an unrecorded external
  models dir; use `-PurgeExternalModels` (or confirm) only for a models path recorded at install.

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
