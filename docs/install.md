# One-click install

Per-user installers for each supported non-server platform. None needs admin or
root. FreeBSD and other server-oriented systems use the manual steps in MANUAL.md.

| Platform | One click | Installs to |
|---|---|---|
| Windows 10/11 | double-click `install\windows\install.bat` (or `powershell -ExecutionPolicy Bypass -File install\windows\install.ps1`) | `%LOCALAPPDATA%\familia`; models on `E:\temp\familia\models` when `E:\temp` exists |
| Desktop Linux (Ubuntu/Debian…) and macOS | `curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install/linux/install.sh \| sh` | `~/.local/share/familia`, launcher `~/.local/bin/familia-start` |
| Android (Termux from F-Droid/GitHub) | `curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install/termux/install.sh \| sh` | `~/familia`, launcher `$PREFIX/bin/familia-start` |

macOS uses the Linux script (README lists macOS as supported); it has been
syntax-checked but **not run on a Mac**.

## What every installer does

1. Clones (or fast-forwards) the repo. Re-running is safe.
2. Gets a llama.cpp CPU runtime:
   - Windows/Linux/macOS: the official ggml-org release asset (default build
     `b11539`, `--build latest` / `-Build latest` for the newest). The sha256 is
     read from the GitHub release API's `digest` field **at install time** and
     checked before extraction. No hash is stored in this repo; if the API
     publishes no digest the installer stops.
   - The Windows `win-cpu-x64` build selects its CPU backend at runtime and runs
     without AVX (verified on qodesh, Athlon II X2).
   - Termux: `pkg install llama-cpp` (signature-checked by pkg).
3. Measures the host (CPU, threads, RAM, CPU flags) and writes `hosts.<name>`
   into `graph.yaml` with `measured: true`. Unreadable values are left out, never
   guessed. `reserve_ram_mib` is set from docs/ram-safety.md policy (3072 MiB under
   12 GiB RAM, else 4096) and labelled as policy. An existing host block is left
   alone unless `--force-host` / `-ForceHost` (which replaces the whole block,
   including hand-written `gpus`/`notes`).
4. Validates the graph (`validate_graph.py --no-files`) when PyYAML is present.
5. Writes a launcher. Optional autostart: `--systemd` (systemd --user unit, written
   but not enabled), `-LogonTask -Model x.gguf` (per-user scheduled task via
   `scripts\windows\install-task.ps1`), Termux:Boot hint. Termux `--sshd` installs
   openssh and starts sshd on port 8022 (key auth).

## Flags

| | Linux/macOS | Termux | Windows |
|---|---|---|---|
| Dry run (changes nothing) | `--dry-run` | `--dry-run` | `-DryRun` or `-WhatIf` |
| Uninstall (keeps models) | `--uninstall` | `--uninstall` | `-Uninstall` |
| Remove everything | `--uninstall --purge` | `--uninstall --purge` | `-Uninstall -Purge` |
| Host name | `--name` | `--name` | `-Name` |
| Skip runtime | `--no-runtime` | `--no-runtime` | `-NoRuntime` |

Safety: no secrets are read or written; downloads are checksum-verified;
nothing runs as root/admin; installers are idempotent. Measuring a host only
records what it is; it does not place any model, so RAM-safety checks in the
validator still decide what can run.
