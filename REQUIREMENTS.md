# REQUIREMENTS.md

> **Status note (2026-10-09):** this file was originally agent-generated session notes for the wrong project name ("Green-Roomz swarm system") and cited files that do not exist. It has been trimmed to requirements that still apply; each item says whether it is **implemented**, **in progress**, or **planned**. Owner: the familia maintainer.

## Overview
High-level requirements for the familia topology coordinator: the Linux orchestrator, Android (Termux) nodes, and a future SSH proxy nexus.

## Core
- **Nodes:** Linux orchestrator (implemented), Android/Termux node over SSH port 8022 (in progress: #14, #15, #18), Windows node (planned: #17).
- **Specialist roles:** pentest and similar roles are declared in the graph and are **launch-tested only** (validate, start, health check, stop; never a live exercise). Typed `pentests` support is on the unmerged `feat/graph-types` branch.
- **Commands:** `/local` and `/remote` routing (implemented in the pinned code-bootstraps-llama.cpp agent, not in this repo).
- **Declarative configuration:** models, runtimes and agents declared in `graph.yaml` and checked by `scripts/validate_graph.py` (implemented; see `docs/configuration-graph.md`).
- **RAM safety:** keep a large reserve on small hosts; `reserve_ram_mib: 3072` on miryam (implemented; see `docs/ram-safety.md`).
- **Tests:** Python unit tests exist for the graph on feature branches; an end-to-end suite and shell syntax CI (`sh -n` / shellcheck) are planned (#14).

## Android node
- Launch via `android_start.sh` with host, port and user from the environment and key-based SSH (#18). Fleet helpers `with-fleet.sh` and `scripts/pentest-role.json` do not exist yet; the script guards against their absence (#15).
- `watchdog_android.sh` monitoring: planned cleanup (password variable name, cwd-relative path, log location).

## SSH proxy nexus (planned)
- Goal: let nodes behind NAT talk via an edge host using `ssh -R` / `-L`.
- Key-only auth, password auth disabled.
- Declarative config in the graph (`hosts` / `transports`). A proof of concept is on the unmerged `feat/transport-poc` branch.

## Removed (stale)
- `scripts/github_issue.sh`, `rebuild_top_level_scripts.sh`, `*.ps1` regeneration, `proxy-nexus-config.json`, and a "99.9 % uptime" target: none existed or were measurable.
