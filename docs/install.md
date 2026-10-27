# One-click install

Per-user installers for each supported non-server platform. None needs admin or
root. FreeBSD and other server-oriented systems use the manual steps in MANUAL.md.
On the FreeBSD test host `angel`, the one-click runtime installer is unsupported;
build the pinned llama.cpp from **code-bootstraps-llama.cpp** source. Use
`sh install/freebsd/deps.sh` (opt-in `--install`) for an honest pkg list (git,
python, cmake, …). `getconf` is in the FreeBSD base. Prebuilt Linux/macOS release
assets do not provide a FreeBSD runtime.

When an installer is run from a familia checkout, it uses that checkout's current
branch for the installed repo and keeps it tracking `origin/<branch>`. Set
`FAMILIA_BRANCH` or pass `--branch BRANCH` (`-Branch BRANCH` on Windows) to choose
a branch explicitly. Running a downloaded installer without a git checkout defaults
a new install to `main`, but an existing install stays on its current tracked branch.
The bootstrap `install.sh` likewise updates an existing checkout from its configured
upstream; it does not force `main`. On FreeBSD, do not run the runtime installer:
select/sync the desired familia branch with `./familia sync --branch BRANCH`, then
build the pinned llama.cpp checkout from source as described above.

| Platform | One click | Installs to |
|---|---|---|
| Windows 10/11 | double-click `install\windows\install.bat` (or `powershell -ExecutionPolicy Bypass -File install\windows\install.ps1`) | `%LOCALAPPDATA%\familia`; models on `E:\temp\familia\models` when `E:\temp` exists |
| Desktop Linux (Ubuntu/Debian…) and macOS | `curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install/linux/install.sh \| sh` | `~/.local/share/familia`, launcher `~/.local/bin/familia-start` |
| Desktop Linux **AppImage** (milestone) | download `familia-*-x86_64.AppImage`, double-click (see [appimage.md](./appimage.md)) | writable checkout `~/.local/share/familia/appimage-checkout`; terminal menu |
| Android (Termux from F-Droid/GitHub) | `curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install/termux/install.sh \| sh` | `~/familia`, launcher `$PREFIX/bin/familia-start` |

macOS uses the Linux script (README lists macOS as supported); it has been
syntax-checked but **not run on a Mac**.

## AppImage (Linux milestone)

Prefer the **AppImage** for a packaged Linux entry: download the `.AppImage` from the release and run it (opens the terminal menu by default; use `--cli` for one-shot commands). Build with `./scripts/build_appimage.sh`. Details: [appimage.md](./appimage.md). Shell installers below remain valid.

## OS packages (every platform)

**Safe-mode priority:** help the user install local packages and **build** before anything fancy. See [safe-mode-bootstrap.md](safe-mode-bootstrap.md). The build-helper AI lives in the pinned **code-bootstraps-llama.cpp** (decision/route GGUF **`Laya-Q8_0.gguf`**; graph alias `safe-build` = SmolLM chat face); familia dispatches into it.

```
sh install/deps.sh                       # detect platform; list present / missing
sh install/deps.sh --install             # install missing (asks)
sh install/deps.sh --yes --install --profile build   # also cmake/ninja/compilers
```

Menu: `setup.deps`. Platform helpers:

| Platform | Script |
|---|---|
| Linux / macOS | `install/linux/deps.sh` (apt/dnf/pacman/zypper/brew) |
| Termux | `install/termux/deps.sh` (`getconf`, `pytest`, …; wired into `install/termux/install.sh`) |
| FreeBSD | `install/freebsd/deps.sh` (honest pkg list; opt-in `--install`) |
| Windows | `install/windows/deps.ps1` (winget/choco hints; few apt-like packages) |

Base profile: `git`, `curl`, `python3`/`python`, `tar`, `unzip`, PyYAML, **pytest**. Build profile adds cmake/ninja/a C++ toolchain for code-bootstraps source builds. `getconf` is base/glibc on Linux/macOS/FreeBSD; on Termux it is the **`getconf`** package.

The top-level bootstrap `install.sh` (clones into `~/familia`, configure + start) is separate from `install/linux/install.sh` (one-click graph-node under `~/.local/share/familia`). Both call the deps helper when tools are missing.

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
   openssh and starts Termux's sshd (key auth).

## familia on your PATH

Every installer ends by putting `familia` on your PATH for your user only (no root, no admin). `--no-path` (Windows `-NoPath`) skips it, and `familia install-cli [--dry-run] [--prefix DIR]` (same as `sh scripts/install-cli.sh`; menu: Set up) does it later from any checkout.

- **The code is not copied.** The only file written is a 2-line shim that runs the checkout's `familia`:
  ```
  #!/bin/sh
  exec '/home/you/.local/share/familia/repo/familia' "$@"
  ```
  A shim, not a symlink: `familia` finds its checkout from `$0`, and old `sh` and BSD `readlink` can't reliably resolve a symlink back to the repo.
- **Where:** `$XDG_BIN_HOME/familia` (default `~/.local/bin/familia`). The man page and bash completion, once the checkout has them (`man/familia.1`, `completions/familia.bash`), are linked into `$XDG_DATA_HOME/man/man1/familia.1` and `$XDG_DATA_HOME/bash-completion/completions/familia` (default `~/.local/share`), where `man` and bash-completion find them on their own. If the checkout doesn't have them yet they're skipped. `--prefix DIR` uses `DIR/bin` and `DIR/share` instead.
- **Termux:** the shim goes in `$PREFIX/bin`, which is already on PATH. **FreeBSD:** the port installs to `/usr/local` as before.
- **Windows:** `%LOCALAPPDATA%\Programs\familia\bin\familia.cmd` (2 lines, `@echo off` + the checkout's `familia.cmd %*`), and that folder is appended to your user PATH in `HKCU\Environment` (kept as `REG_EXPAND_SZ`). `-WhatIf` previews. `scripts\windows\install-cli.ps1 -Uninstall` removes the shim and the PATH entry only if it added them.
- **PATH:** most distros already put `~/.local/bin` on PATH. If yours doesn't, the installer prints the one line to add, `export PATH="$HOME/.local/bin:$PATH"`, and changes no rc file. `familia path --add` (or `sh scripts/install-cli.sh path --add`) shows a block and asks before adding it to `~/.profile`:
  ```
  # >>> familia >>>
  # added by `familia path --add`; `familia path --remove` deletes this block
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
  # <<< familia <<<
  ```
  Running it again changes nothing. `path --remove` deletes only the lines between the markers. `--yes` answers the question for scripts. If you have `~/.bash_profile` or `~/.bash_login`, bash login shells read that instead of `~/.profile`, and it's pointed out.
- **Uninstall:** every file written is recorded in `$XDG_STATE_HOME/familia/installed.txt` (default `~/.local/state`). `familia uninstall-cli` (`sh scripts/install-cli.sh uninstall`) lists what it would remove and asks; `--dry-run` only lists it, and without a terminal it only lists unless you pass `--yes`. It removes only those files, and only while they are still a familia shim or link (a file you replaced is kept), plus the `~/.profile` block. The installers' `--uninstall` does this too.
- **Status:** `familia install-cli status` (Windows `-Status`).

## Flags

| | Linux/macOS | Termux | Windows |
|---|---|---|---|
| Dry run (changes nothing) | `--dry-run` | `--dry-run` | `-DryRun` or `-WhatIf` |
| Uninstall (keeps models) | `--uninstall` | `--uninstall` | `-Uninstall` |
| Remove everything | `--uninstall --purge` | `--uninstall --purge` | `-Uninstall -Purge` |
| Host name | `--name` | `--name` | `-Name` |
| Familia branch | `--branch BRANCH` | `--branch BRANCH` | `-Branch BRANCH` |
| Skip runtime | `--no-runtime` | `--no-runtime` | `-NoRuntime` |
| Don't put `familia` on PATH | `--no-path` | `--no-path` | `-NoPath` |

Safety: no secrets are read or written; downloads are checksum-verified;
nothing runs as root/admin; installers are idempotent. Measuring a host only
records what it is; it does not place any model, so RAM-safety checks in the
validator still decide what can run.
