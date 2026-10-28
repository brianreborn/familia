# Testing familia (v0.1.0-rc2)

This page is for anyone who wants to try familia on their own hardware and report back.
Everything here works from a plain checkout of `main` (or the `v0.1.0-rc2` tag). File
issues at https://github.com/brianreborn/familia/issues and include the output of the
validator and test runs below.

## 1. Quickstart per platform

All installers are per-user (no root/admin), idempotent, checksum-verify what they
download, and support a dry run. Details and flags: [docs/install.md](docs/install.md).

| Platform | One click | Dry run |
|---|---|---|
| Desktop Linux (Ubuntu/Debian, also macOS, untested on a Mac) | `curl -fsSLo install-familia-node.sh https://raw.githubusercontent.com/brianreborn/familia/main/install/linux/install.sh; sh ./install-familia-node.sh` | add `--dry-run` |
| Windows 10/11 | double-click `install\windows\install.bat` (or `powershell -ExecutionPolicy Bypass -File install\windows\install.ps1`) | `-DryRun` |
| Android (Termux from F-Droid/GitHub) | `curl -fsSLo install-familia-termux.sh https://raw.githubusercontent.com/brianreborn/familia/main/install/termux/install.sh; sh ./install-familia-termux.sh` | add `--dry-run` |

Each installer clones the repo, fetches a llama.cpp CPU runtime (ggml-org release with the
sha256 checked at install time; Termux uses `pkg install llama-cpp`), measures the host and
writes `hosts.<name>` into `graph.yaml` (`measured: true`, nothing guessed), validates the
graph, and writes a launcher (`familia-start`, or `scripts\windows\start.bat`). Windows
specifics: [docs/windows.md](docs/windows.md).

From a checkout instead:

```sh
git clone https://github.com/brianreborn/familia && cd familia
python3 -m pip install --user pyyaml pytest      # plus gguf and "$(python3 scripts/cpu_level.py --numpy-spec)" for the LittleBit tests
```

## 2. Validator and tests

```sh
python3 scripts/validate_graph.py --no-files     # schema + placement rules only (no model files needed)
python3 scripts/validate_graph.py                # also reads GGUF headers and checks RAM/VRAM on this host
python3 scripts/validate_graph.py --args NODE    # print the llama-server args for one node
python3 -m pytest -q                             # unit tests
bash tests/test_with_fleet.sh                    # repo/fleet wiring smoke test
bash tests/test_nexus_localhost.sh               # ssh nexus on localhost (needs sshd binary)
bash tests/test_bt_loopback.sh                   # private bittorrent loopback
```

On Windows set `PYTHONUTF8=1` first. Test counts vary with optional tools and local model files;
pytest reports unavailable prerequisites as skips. On Linux, the full suite passed on
2026-10-22 (654 passed, 24 skipped). Skips need llama-server binaries, model files, or network.

Initial cross-platform coverage targets are Ubuntu, Windows 10/11, FreeBSD, and Samsung Android
through Termux. Run the Python suite where supported; platform checks also cover the native menu,
host measurement, and runtime build/launch paths. Results on one platform do not imply validation
on the others.

### Acceptance for substantial features and model configurations

The Python suite is necessary, but it is not a substitute for end-to-end task-suite evidence.
Substantial feature changes need a real integrated-path test with representative inputs. A new
or materially changed model configuration stays planned/experimental until it passes a fixed
role-appropriate task suite against a baseline using the same tasks. Define pass criteria before
the run and record the exact model/runtime (name + version, not hash-only), configuration and
prompt/template labels, suite revision, seed, platform class, per-task results, aggregate, and
known limitations. Use each platform the feature claims to support where relevant; the initial
targets are Ubuntu, Windows, FreeBSD, and Samsung Android/Termux (A57-class phones; not
Note9-only). Full gate, fixed suite, result schema, runner, and promote refuse logic:
[docs/testing/task-suite-acceptance.md](docs/testing/task-suite-acceptance.md)
([#119](https://github.com/brianreborn/familia/issues/119)). Quick checks:

```sh
python3 scripts/task_suite_runner.py --dry-run --role coder --platform ubuntu
python3 scripts/task_suite_promote.py check --role coder --model-name 'Example' --radical-trigger quantization
python3 -m pytest -q tests/test_task_suite_gate.py
```

Pentest tests remain launch-test-only.

- Windows without bash: 3 tests fail because they shell out to `bash`
  (`test_android_targets::test_scripts_have_no_hardcoded_targets_or_sshpass`,
  `test_installers::test_host_measure_insert_and_idempotent`, `test_installers::test_installer_shapes`).
  They pass under Git Bash/WSL or on Linux. Everything else passes.
- The validator prints `WARNING: ... no registry record` for nodes that have no measurement yet. That is informational.

## 3. Try the agent: hermes.sh

Use the harness, not stock `hermes`: `~/.hermes` has compression off and small-context models, and fails with HTTP 400 on long turns ([QUICKSTART.md](QUICKSTART.md#always-run-hermes-through-the-harness)).

```sh
scripts/hermes.sh --render-only            # print the hermes-agent config generated from graph.yaml, start nothing
scripts/hermes.sh --selftest-compaction    # check context compaction against the node's per-slot ctx
scripts/hermes.sh [--agent NAME] -- ARGS   # launch hermes-agent against the graph
```

The agent's `context_length` must equal the serving node's per-slot ctx (`ctx / parallel`);
the validator refuses a mismatch (LESSONS-LEARNED L2).

## 4. Legacy GPU path: GeForce 8600 GT (sm_11) on Windows

`gpu-legacy/` runs SmolLM2-135M and llama2.c checkpoints on a 2007-era sm_11 card through the
CUDA *driver* API and hand-written PTX (`kernels.ptx`, `matvec_sm11.ptx`). No CUDA toolkit or
MSVC is needed. It needs the NVIDIA 341.x driver (`nvcuda.dll`) and a mingw-w64 gcc (for example a
portable WinLibs gcc; the example below assumes it is unpacked at `E:\temp\tools\mingw64`).

```bat
cd gpu-legacy
set PATH=E:\temp\tools\mingw64\bin;%PATH%
mkdir out
gcc -O2 -march=native -o out\smol_sm11.exe smol_sm11.c -lm
build-gcc.bat                                   :: llama2.c runner -> out\run_sm11.exe
out\smol_sm11.exe SmolLM2-135M-Instruct.Q4_0.gguf "1,2,3" 32 both   :: cpu | gpu | both (both checks GPU == CPU per token)
```

Result on qodesh (Athlon II X2, 8600 GT 256 MiB shared with the desktop): 4.5 -> 15.3-16.9 tok/s
over 2026-10-09/10, matching the CPU on every token. Full story:
[gpu-legacy/LESSONS-LEARNED.md](gpu-legacy/LESSONS-LEARNED.md), sync model:
[gpu-legacy/SYNC-AUDIT.md](gpu-legacy/SYNC-AUDIT.md).

Useful environment variables (defaults are the tuned values):

| Variable | Default | Meaning |
|---|---|---|
| `SMOL_FUSED` | 1 | fused Q4/Q8 matvec, RoPE+KV and multi-head attention kernels; `0` = unfused path |
| `SM11_VRAM_MARGIN_MIB` | 16 | VRAM left free for the desktop before weights go resident |
| `SM11_PTX` | `kernels.ptx` | path to the PTX module |
| `SMOL_CTX` | 128 (max) | context length |
| `SMOL_CLS` | q8 | classifier quant (`q4` when VRAM is short) |
| `SMOL_TEX` | auto | read the classifier through the texture cache |
| `SMOL_X` / `SMOL_MR` | 1 / 2 | per-shape tuned v6 kernels / rows per thread for the fallback kernel |
| `SMOL_PRENORM`, `SMOL_WAIT` | 1, 1 | rmsnorm once per token; overlap host work while waiting on the token event |
| `SMOL_KBENCH`, `SMOL_KB_REPLAY` | off | kernel tuner; replay mode times real token forwards |
| `FAMILIA_GPU`, `SM11_RESIDENT_MIB` | (run_sm11) | route llama2.c matmuls to the GPU; cap resident VRAM |

## 5. Phones: Vulkan on Android (Termux)

Verified on Samsung A57 (Exynos 1680, Xclipse 550); profile in
`registry/hardware/samsung-a57-sm-a576u-exynos1680-android16.yaml`.

```sh
pkg install llama-cpp llama-cpp-backend-vulkan
mkdir -p ~/.vk
ln -sf /system/lib64/libvulkan.so ~/.vk/libvulkan.so
ln -sf /system/lib64/libvulkan.so ~/.vk/libvulkan.so.1   # both names are needed
export LD_LIBRARY_PATH=$HOME/.vk                          # Termux's own loader only sees llvmpipe
termux-wake-lock                                          # before any long run, or Wi-Fi drops
sshd                                                      # optional, key auth only
llama-bench -m SmolLM2-135M-Instruct-Q4_K_M.gguf -ngl 99
```

Measured: SmolLM2-135M 66-79 tok/s on Vulkan vs ~30 on the CPU. Record `llama-server --version`
with every result; two "identical" phones had different Termux llama-cpp versions (L9).

Termux add-ons (Termux:API, Termux:Boot, ...) must be signed with the same key as Termux itself. Our phones run Termux from the latest GitHub build, so Termux:API must come from https://github.com/termux/termux-api/releases (not F-Droid, not Play). The `termux-api` pkg alone is not enough: `termux-battery-status` hangs without the app. Power readings without it use readable `/sys/class/power_supply/*` files only.

## 6. Registry: reuse measurements instead of re-tuning

```sh
python3 scripts/registry.py summarize
python3 scripts/registry.py suggest --host miryam --role decision --graph graph.yaml
python3 scripts/registry.py match --graph graph.yaml --host phone8   # known-good setup for identical hardware
python3 scripts/registry.py power                                    # watts (spec-sheet estimates unless measured)
python3 scripts/registry.py add result.json                          # append your own measured result
```

Results live in `registry/records.jsonl` (append-only, each labelled measured or estimated).
Hardware profiles in `registry/hardware/` contain no hostnames, IPs or users, so they are safe to
contribute back. The registry never edits `graph.yaml`; it prints snippets. See
[docs/model-registry.md](docs/model-registry.md).

## 7. RAM-safety rules (please follow them when testing)

From [docs/ram-safety.md](docs/ram-safety.md). The validator fails on a clear overcommit and warns on the first two.

1. Every host keeps `reserve_ram_mib` free: 3072 MiB on machines under 12 GiB, otherwise 4096.
2. On hosts with less than 8 GiB, estimated use must leave at least 2048 MiB free.
3. Small hosts run one heavy process at a time: no coder server plus embedding test plus
   benchmark together (a 7 GiB laptop hard-hung that way, L4).
4. iGPU memory is system RAM: anything loaded on an integrated GPU counts against the same budget.
5. Benchmarks and tuning scripts should check free RAM first and stop, not kill other processes.

## 8. Known limitations

- `ssh chat.hf.co` (Qwen3.8-27B) and LittleBit QAT on HF Jobs need Hugging Face credits; neither runs without them.
- LittleBit conversion needs a user-supplied checkout of SamsungLabs/LittleBit (CC BY-NC 4.0, not vendored).
  `lbref` is a numpy reference runtime for correctness only; llama.cpp cannot load `.lbit.gguf`. See [docs/littlebit.md](docs/littlebit.md).
- The FreeBSD port (`packaging/freebsd/`) is untested.
- macOS uses the Linux installer and has only been syntax-checked.
- The 8600 GT path is Windows-only and specific to sm_11 cards with the 341.x driver; the card is shared
  with the desktop, so results vary with desktop load.
- On miryam's HD 620 the iGPU is slower than the CPU for generation and slows the CPU coder when both run
  (shared memory bus and power budget); prompt-processing and embedding use of the iGPU is still being measured.
- The phone parameter sweep (quants, KV type, flash attention, threads, batch) has not finished yet.
- More: [docs/known-issues.md](docs/known-issues.md).

## Windows prerequisites

- **bash:** use Git for Windows' bash, not WSL's `C:\Windows\System32\bash.exe`. Put `C:\Program Files\Git\bin` and `C:\Program Files\Git\usr\bin` on your user PATH.
- **Python 3.12** from python.org, with `set PYTHONUTF8=1`. The bash tests call `python3`, so either disable the Microsoft Store "App execution aliases" for python3, or add a shim named `python3` that runs `exec python "$@"`.
- **numpy:** run `pip install --user "$(python scripts/cpu_level.py --numpy-spec)"` (on Windows: `python -m pip install --user (python scripts\cpu_level.py --numpy-spec)`). The choice depends only on the CPU's x86-64 level. Below v2 (no SSSE3/SSE4.1/SSE4.2/POPCNT, e.g. Athlon II X2) you get `numpy<2.4`, because NumPy 2.4.0 raised its wheel baseline to X86_V2 and those wheels crash with 0xc000001d. Everything else, including ARM, gets current numpy. On v0/v1 Windows with Python 3.12 the installer first tries our own numpy 2.5.3 wheel built with `-Dcpu-baseline=none` (release asset; rebuild with `scripts\build_numpy_wheel.ps1`, needs MSYS2 ucrt64 gcc), then falls back to `numpy<2.4`. That wheel is experimental: long double (`np.longdouble`) math can crash it; familia never uses long double. See LESSONS-LEARNED.md.
- **pytest:** `python -m pytest -q tests`. Expected: everything passes or skips except the known `test_overcommit_is_hard_error` failure and the bash-dependent tests listed in section 2.
- **bash tests:** `test_nexus_localhost.sh` is Linux-only because it needs sudo/useradd. `test_bt_loopback.sh` needs `aria2c`. `test_with_fleet.sh` needs the graph's model files to be present.
