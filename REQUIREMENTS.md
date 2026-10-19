# REQUIREMENTS.md

> **Status note (2026-10-10):** trimmed from earlier session notes; each item says whether it is **implemented**, **in progress**, or **planned**. Owner: the familia maintainer.

## Overview
High-level requirements for the familia topology coordinator: the Linux orchestrator, Android (Termux) nodes, Windows nodes, and a future SSH proxy nexus.

## Core
- **Nodes:** Linux orchestrator (implemented), Android/Termux node over SSH port 8022 (in progress: #14, #18), Windows node (in progress: #17; `scripts/windows/start.bat` on main).
- **Specialist roles (pentest):** declared in the graph under `pentests` (implemented on `main`; see `docs/graph-types.md`, `docs/pentest-models.md`). **Launch-tested only.** Automation may only validate → start → healthcheck → stop. Never fully exercise attack tools, live scans, exploits, or network probes in tests or PoCs.
  - **Tools double-disabled for launch-tests (required):** every automated pentest launch-test MUST disable tools in **two independent ways** before any process starts. Acceptable pairs today: (1) empty `tools.allow: []` in both `graph.yaml` `pentests.*` and `scripts/pentest-role.json`, and (2) `launch_test_only: true` so `with-fleet.sh` refuses to start tool-capable paths (and the hermes agent / toolsets are not started). Empty `scope.allow: []` is additional hard deny, not a substitute for the second tools disable. Never remove either disable for CI or smoke tests.
- **Commands:** `/local` and `/remote` routing (implemented in the pinned code-bootstraps-llama.cpp agent, not in this repo).
- **Declarative configuration:** models, runtimes and agents declared in `graph.yaml` and checked by `scripts/validate_graph.py` (implemented; see `docs/configuration-graph.md`).
- **RAM safety:** keep a large reserve on small hosts; `reserve_ram_mib: 3072` on miryam (implemented; provisional guidance — see `docs/ram-safety.md`).
- **Tests:** Python unit tests for the graph and registry (implemented); shell syntax CI (`sh -n` / shellcheck) planned (#14).

## Model database (planned: #51)
- **Full Hugging Face repo, pinned:** every model gets a database entry built from the *entire* upstream HF repo at a pinned revision (commit SHA), not a lone `.gguf`. That covers the model card `README.md`, `config.json`, `generation_config.json`, tokenizer and chat-template files, the license, and the base repo when the GGUF is a third-party quant. Record a sha256 for each file.
- **Use all of it:** the card's recommended sampling parameters, context length and RoPE/YaRN scaling, thinking modes, chat template, system-prompt rules, stop tokens and documented command lines become the node's launch defaults (serve.sh/ps1, hermes harness). Any deviation must be recorded explicitly with a reason.
- **Fail loud:** `validate_graph.py` rejects a node whose model has no database entry, or whose settings contradict the card without a recorded override. Registry benchmark records reference the entry, so results are reproducible with card-correct settings.
- **Old hardware still wins:** the fetch skips weight files we don't use, so entries stay small enough for ~15-year-old devices.

## Android node
- Launch via `android_start.sh` with host, port and user from the graph / environment and key-based SSH (#18). Fleet helpers `with-fleet.sh` and `scripts/pentest-role.json` are on `main` (fixes #15); pentest role remains launch-test only.
- `watchdog_android.sh` monitoring: planned cleanup (password variable name, cwd-relative path, log location).

## SSH proxy nexus (planned)
- Goal: let nodes behind NAT talk via an edge host using `ssh -R` / `-L`.
- Key-only auth, password auth disabled.
- Declarative config in the graph (`hosts` / `transports`). A proof of concept is on the unmerged `feat/transport-poc` branch.

## Removed (stale)
- `scripts/github_issue.sh`, `rebuild_top_level_scripts.sh`, `*.ps1` regeneration, `proxy-nexus-config.json`, and a "99.9 % uptime" target: none existed or were measurable.
