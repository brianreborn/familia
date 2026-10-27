# Safe-mode bootstrap — help people **build**

**Priority (Brian, 2026-10-27):** familia grew complicated; the beginning is still
helping someone on any machine install local packages and **build** software with a
tiny local AI. That AI lives in the pinned component
[`code-bootstraps-llama.cpp`](https://github.com/brianreborn/code-bootstraps-llama.cpp)
(see `pins.txt`), not a parallel familia-only stack. Familia’s job here is to
**dispatch into** that component: deps scripts, installers, and a small
decision/route-sized model that helps build — not a full coding agent.

## Goal

A **safe-mode** path that works on every platform familia cares about:

| Platform | Deps helper | Build home |
|---|---|---|
| Linux / macOS | `install/linux/deps.sh` (via `install/deps.sh`) | `code-bootstraps-llama.cpp` → `scripts/build-linux.sh` / `start.sh` |
| Android Termux | `install/termux/deps.sh` (and Termux `install.sh` PKGS) | `scripts/build-termux.sh` / Android release asset |
| FreeBSD (angel) | `install/freebsd/deps.sh` (opt-in `pkg install`) | `BUILD_DIR=build-freebsd GPU=off scripts/build-linux.sh` |
| Windows | `install/windows/deps.ps1` (winget/choco hints) | `scripts\build-windows.ps1` / `start.bat` |

Unified entry:

```sh
sh install/deps.sh                 # list present / missing
sh install/deps.sh --install       # install missing (asks)
sh install/deps.sh --yes --install --profile build   # also cmake/ninja/compilers
```

Menu: **`setup.deps`** (“Install local OS packages this host needs”).

## What “safe-mode model” means

- **Always-on, small, CPU-friendly** — same size class as the existing SmolLM2-135M
  **decision** nodes (`box-decision`, phone/qodesh decision cards) and
  code-bootstraps’ **route** / light **chat** models.
- Helps **install packages, configure toolchains, and build** (llama.cpp, local
  tools). It does **not** need to be a strong coder.
- Non-goals: full Hermes-class coding agent, fleet orchestration, pentest roles.

The graph stub for a dedicated `safe-build` alias is noted next to `aliases:` in
`graph.yaml` (points at the decision-size pattern / code-bootstraps route). Do not
activate a heavy model for this role.

## Termux packages (phones)

Default `install/termux/install.sh` PKGS now include:

- `git`, `python`, **`getconf`** (confirmed package name), `llama-cpp` (when runtime on), `openssh` (with `--sshd`)
- **pytest** via `python-pytest` when the Termux index has it, else `pip install pytest`
- `pyyaml` via pip (graph validation)

Build profile (`--profile build`): `clang`, `cmake`, `ninja` — matches
code-bootstraps `build-termux.sh`.

## GPU default: `auto`, not unjustified `none`

Host GPU `backend` may be `auto` (prefer a real backend when measured) or a concrete
backend (`cuda`, `cuda-sm11-ptx`, `vulkan`, …). Use `none` only when the hardware
truly has no usable GPU API (e.g. godslove Ironlake, `backend_status: unsupported`).
Offload still requires a concrete verified backend — `auto` / `none` are inventory
labels, not `-ngl` targets. See `docs/graph-types.md` and centos10-bigram (#113).

## Installer wiring

- Top-level `install.sh` runs `install/deps.sh` after clone when python/curl are missing.
- `install/linux/install.sh` calls the dispatcher before dying on missing tools.
- Termux installer installs the expanded PKGS by default.

## What’s left (model itself)

1. Pin / document which code-bootstraps GGUF is the safe-mode build helper (route or
   smallest chat).
2. Optional always-on `safe-build` node (planned → active) on weak hosts, CPU only.
3. Prompt / system text: “help the user install packages and build; do not pretend
   to be a full coding agent.”
4. Cross-link from code-bootstraps README back to this doc when the pin moves.

Until then: **`setup.deps` + code-bootstraps `./start.sh`** is the safe-mode path.
