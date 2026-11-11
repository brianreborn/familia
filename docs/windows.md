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
keep them equal to the node in `graph.yaml`. An API key is required on every bind, including
loopback (DESIGN.md Security): `start.bat` passes `--api-key-file` from
`%APPDATA%\familia\instances\<port>\api-keys` (created once) and runs
`scripts\bind_auth_guard.py` before starting the server (as a child of cmd, not exec).
Set `FAMILIA_API_KEY_FILE` or `API_KEY_FILE` to override the path; both names are
accepted by `familia_auth` clients. This per-instance file is the canonical layout
for graph-launched nodes; `familia-start` uses `api.key` instead, and there is no
migration yet ([#419](https://github.com/brianreborn/familia/issues/419)).
Python 3 is required for the guard. On Windows the POSIX 0600/0400 mode check is skipped;
the file lives under the current user's `%APPDATA%`, and no ACL check is performed yet.
`start.bat` and `serve.sh` unset `LLAMA_API_KEY` and every `LLAMA_ARG_*` variable
(including `LLAMA_ARG_SSL_*`) so they cannot bypass the argv checks. `FAMILIA_EXTRA`
is passed unquoted after `--extra-start` so the guard and llama-server split the same
tokens. cmd metacharacters in `FAMILIA_EXTRA` are unsupported.

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
