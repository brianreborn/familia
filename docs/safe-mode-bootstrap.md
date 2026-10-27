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

Menu: **`setup.deps`** (“Install local OS packages this host needs”),
**`setup.safe-build`** (show the pinned build-helper GGUF and how to reach it).

## Pinned build-helper GGUF (code-bootstraps)

| Field | Value |
|---|---|
| Role in code-bootstraps | **`decision`** (router alias **`route`**) |
| File | **`Laya-Q8_0.gguf`** |
| HF | [`ggml-org/Laya-GGUF`](https://huggingface.co/ggml-org/Laya-GGUF) @ `da4b4753d62197659d8c90103cd4c43bef9afea6` |
| Size / quant | ~449 MB, Q8_0 |
| sha256 | `c06528c5746d3bb8baa72a27938be95abbfd0b226f8471e8a9e365ed0bb066d2` |
| Manifest | `code-bootstraps-llama.cpp/config/models-manifest.json` (`pick=default`, `role=decision`) |
| Endpoint | `POST /v1/systemone` (not chat) |

This is already the **default** decision model in the pinned component — no new
download. Familia does not re-host the weights; it syncs the pin via `pins.txt`
and dispatches (`./start.sh --bootstrap`, deps helpers, graph alias).

### Chat face for build help (familia graph)

Laya evaluates the whole prompt in one batch for **routing**; it cannot hold a
deps/build conversation. For that, graph alias **`safe-build`** points at the
existing SmolLM2-135M decision-size node **`miryam-gpu-decision`**
(`SmolLM2-135M-Instruct.Q4_0`, role `decision`) — same size class, already
verified on miryam/phones. System text:
[`harness/safe-build/systemprompt.md`](../harness/safe-build/systemprompt.md).

When using code-bootstraps alone (`./start.sh` / `--bootstrap`), light **chat**
is the `general` role (default `LFM2.5-1.2B-Instruct-Q4_K_M`; weakest devices
may use `--fallback` → `LFM2.5-350M-Q4_K_M`). Do not activate a Hermes-class
coder for safe-mode.

## What “safe-mode model” means

- **Always-on, small, CPU-friendly** — decision/route size (Laya) or SmolLM-scale
  chat for Q&A; never a full coding agent.
- Helps **install packages, configure toolchains, and build** (llama.cpp, local
  tools).
- Non-goals: full Hermes-class coding agent, fleet orchestration, pentest roles.

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

## Path today

1. **`setup.deps`** / `sh install/deps.sh --install [--profile build]`
2. **`setup.safe-build`** — print the Laya pin + SmolLM chat-face notes
3. Build / serve from the pin: `./start.sh --bootstrap` (code-bootstraps router)
   or graph gateway alias **`safe-build`** once `miryam-gpu-decision` is active

## Still optional (follow-up)

1. Always-on dedicated `safe-build` **CPU** node (planned → active) on weak hosts —
   beyond the alias stub → `miryam-gpu-decision`.
2. Cross-link from the **code-bootstraps** README back here if/when the decision
   default GGUF moves off Laya.
