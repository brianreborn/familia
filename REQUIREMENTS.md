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

## Model database (implemented: #51; see `docs/model-database.md`)
- **Full Hugging Face repo, pinned (implemented):** every model in use has an entry in `registry/models/<id>.json`, built by `scripts/model_db.py` from the *entire* upstream HF repo at a commit SHA (`scripts/hf_fetch.py`, stdlib urllib, `HF_TOKEN` honoured and never printed): model card, `config.json`, `generation_config.json`, tokenizer and chat-template files, license, and the base repo for third-party quants. Every fetched file is verified (LFS sha256 or git blob sha1); weights over 50 MB are listed with size and LFS sha256 but not downloaded. Snapshots live in `~/.local/share/gguf/hf-meta/ORG--NAME/<sha>/`. `scripts/model_db.py backfill` covers the code-bootstraps manifest, `graph.yaml`, registry records, local model dirs and the HF cache; `add-model.sh --fetch` does the same for new models.
- **Use all of it (implemented for sampling and context; in progress for the rest):** the card's recommended sampling set (chosen by the card's stated default mode, else `generation_config.json`), context length, thinking-mode default, command lines and usage notes are recorded per entry. Sampling becomes the launch default: `validate_graph.py --args` (familia `scripts/serve.sh`, `scripts/hermes_harness.py`) passes the card's flags, and code-bootstraps' `config/models-preset.ini` follows the cards (`scripts/check-card-defaults.py`). RoPE/YaRN, stop tokens and chat template are recorded but not yet applied or checked at launch (in progress).
- **Fail loud (implemented):** `validate_graph.py` rejects a model without an entry or a pinned revision, and a node whose ctx, `sampling` or `card_set` differs from the card without `override_reasons` (each a written reason). Registry records carry `model.db_id` / `model.revision` where the match is unambiguous; the rest have `db_id: null` and a `db_note`.
- **Old hardware still wins (implemented):** stdlib only, no weights fetched; the 20 current entries' snapshots total about 353 MB.

## Android node
- Launch via `android_start.sh` with host, port and user from the graph / environment and key-based SSH (#18). Fleet helpers `with-fleet.sh` and `scripts/pentest-role.json` are on `main` (fixes #15); pentest role remains launch-test only.
- `watchdog_android.sh` monitoring: planned cleanup (password variable name, cwd-relative path, log location).

## SSH proxy nexus (planned)
- Goal: let nodes behind NAT talk via an edge host using `ssh -R` / `-L`.
- Key-only auth, password auth disabled.
- Declarative config in the graph (`hosts` / `transports`). A proof of concept is on the unmerged `feat/transport-poc` branch.

## Removed (stale)
- `scripts/github_issue.sh`, `rebuild_top_level_scripts.sh`, `*.ps1` regeneration, `proxy-nexus-config.json`, and a "99.9 % uptime" target: none existed or were measurable.
