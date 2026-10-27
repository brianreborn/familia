<!-- DRAFT — not published. Placeholders (<VERSION>, <DATE>, <RELEASE_URL>) must be filled and every item confirmed merged before release. -->

# Changelog

All notable changes to familia are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

<!-- Draft. Before release: replace <VERSION>/<DATE>, delete any line whose PR did not merge,
     and fill in PR links. Entries for #14–#19 assume the open fixes land in this release. -->

## [Unreleased]

Landed on `main` after `v0.1.0-rc2`.

### Added
- Model database (`registry/models/`, `scripts/model_db.py`, `scripts/hf_fetch.py`): one entry per model from its full Hugging Face repo pinned to a commit; model-card sampling becomes the launch default and the validator fails on unexplained differences. (#51)
- `add-model.sh` takes a Hugging Face snapshot directory, explicit flags or a lone GGUF, picks up auxiliary models (`--aux`, mmproj/draft/MTP files), and infers the role.
- Semi-automatic light-to-heavy escalation: `escalates_to` / `escalation` node fields, `scripts/escalate.py`, and `scripts/hermes.sh --escalate` with a localhost proxy. Default mode `suggest`; cross-host targets need recorded consent. (#39 tracks the router hookup and live swap.)
- `selection: default|fallback` node field; `qodesh-resident` (Qwen3.5-2B) is a user-selectable fallback on qodesh.
- Pentest launch-test rule: tools disabled two independent ways.

### Fixed
- Vulkan builds no longer allocate ~1.8 GB of unused shared memory on `-ngl 0` nodes: `scripts/serve.sh` and the hermes harness export an empty `GGML_VK_VISIBLE_DEVICES`. (#40 tracks live verification.)
- Prompt cache sized per profile in the pinned code-bootstraps-llama.cpp (#16 there). (#41 tracks live verification.)

### Removed
- Settings panel application (`scripts/panel.py`, `scripts/panel_familia.py`, `docs/panel.md`, FreeBSD `familia-panel`, AppImage panel default). Use terminal `familia settings` / `setup.settings`. `familia panel` remains an alias to settings.

### Documentation
- README, QUICKSTART, MANUAL rewritten as one entry path; configuration-graph and graph-types describe schema v2 on `main`; LAN addresses removed from public docs.

## [0.1.0-rc1] - 2026-10-10

Pre-release for outside testers; start with [TESTING.md](../../TESTING.md).

### Added
- `TESTING.md`: per-platform quickstart, validator/tests, hermes.sh, legacy GPU, phone Vulkan, registry, RAM-safety rules, known limitations.
- Legacy GPU path for the GeForce 8600 GT (sm_11) on Windows: hand-written PTX through the CUDA driver API, whole-forward-pass on device (`gpu-legacy/smol_sm11.c`). SmolLM2-135M went from 4.5 to 15.3-16.9 tok/s, token-identical to the CPU (fused kernels, texture-cache classifier, per-shape rows-per-thread tuning, replay-based tuner). `gpu-legacy/LESSONS-LEARNED.md`, `gpu-legacy/SYNC-AUDIT.md`. (#24)
- CPU coder + GPU decision node placement on qodesh: coder 1 thread pinned to CPU0 plus GPU node on CPU1, ~30 tok/s combined.
- Android Vulkan: Xclipse 550 via the system libvulkan; SmolLM2-135M 66-79 tok/s vs ~30 on CPU (phone7, phone8).
- miryam HD 620 Vulkan measurements (46 tok/s alone vs 101 on CPU; contention when run beside the coder). (#24)
- Model registry (`registry/records.jsonl`, `scripts/registry.py` add/query/summarize/suggest/match/power/lint) and shareable hardware registry (`registry/hardware/`); the validator warns about nodes with no measurements.
- LittleBit sub-1-bit pipeline: converter to `.lbit.gguf`, numpy reference runtime `lbref`, `scale_down.py --method littlebit`, sm_11 sign-matmul kernel spec. (#28)
- Models catalog (`docs/models-catalog.md`). (#20)

### Changed
- LittleBit support ported to graph schema v2: `models.*.quant: littlebit`, runtime `kind: reference` with `quants: [littlebit]`; `validate_graph.py --args` refuses non-llama-server runtimes.
- `scale_down.py --replace` repoints aliases to the scaled node.
- `.gitignore` now excludes build outputs, logs and model files.

## [<VERSION>] - <DATE>

First tagged release.

### Added
- Top-level topology coordinator: `pins.txt` pins sub-projects by revision (code-bootstraps-llama.cpp, green-roomz, green-agentz, green-agency, Agent-Reach), and `scripts/configure.sh` checks them out or links existing sibling checkouts.
- Two-click installer `install.sh` (POSIX sh) with voluntary-contribution acknowledgement; `INSTALL_ACK=yes`, `INSTALL_PREFIX`, `INSTALL_NO_START=1`.
- `start.sh` launcher with `DETACH_MODE=foreground|nohup|tmux|screen`.
- Engine coexistence: `<executable>__<author>__<branch>` naming and per-build isolation; `ENGINE_<ROUTE>` selection; runtime pin for the experimental DReX-DLM engine (`llama-server__nace-ai__edlm`). (#10)
- `scripts/panel.py` proxy to the settings panel on `127.0.0.1:9932`.
- `scripts/retry_wrapper.py` helper for transient model-service errors (not wired into callers yet).
- CodeQL workflow.

### Changed
- Project renamed from feeldznutts to familia across scripts and docs. (#12, #13)
- Installer now clones `brianreborn/familia` into `~/familia` by default. `FAMILIA_REPO_URL` replaces `FEELD_REPO_URL` (old name still honored, with a deprecation warning). (#16)
- Remaining `feeldznutts` log prefixes and the `feeld.env` / `feeld-server` names replaced (`familia.env`, `familia-server`; an existing `feeld.env` is migrated). (#16)
- Windows: one-click installer `install\windows\install.bat` / `install.ps1`, `scripts\windows\start.bat` and an opt-in logon task. Docs no longer reference unshipped top-level `install.ps1` or `scripts/configure.ps1`. (#16, #17)
- Android scripts read host, port and user from the environment; host keys use `accept-new`; no unprompted `sudo` installs. (#18)

### Fixed
- Termux: server survives backgrounding; wake lock held while running. (#7)
- `android_start.sh` syntax error (unbalanced quote). (#14)
- `android_start.sh` no longer fails on missing `with-fleet.sh` / `scripts/pentest-role.json` / `start-green-roomz.sh`. <!-- describe actual fix: added vs guarded --> (#15)
- hermes-agent context overflow against the 16k `coder` slot when compaction is off: <describe fix: docs/config guidance and/or validation>. (#19)

### Documentation
- New README (quick start, architecture, sub-projects from `pins.txt`).
- `docs/configuration-graph.md` design draft.
- Known issues updated for #14–#19. Repost triage table for #20.

### Security
- Android helpers no longer disable SSH host-key checking or pass passwords on the command line. (#18)
