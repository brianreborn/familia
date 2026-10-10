<!-- DRAFT — not published. Placeholders (<VERSION>, <DATE>, <RELEASE_URL>) must be filled and every item confirmed merged before release. -->

# Changelog

All notable changes to familia are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

<!-- Draft. Before release: replace <VERSION>/<DATE>, delete any line whose PR did not merge,
     and fill in PR links. Entries for #14–#19 assume the open fixes land in this release. -->

## [Unreleased]

### Planned
- Declarative configuration graph: models and agents declared explicitly and validated against measured hardware, with no silent model choice, no silent context inflation, and a loud failure on mismatch. Design draft: `docs/configuration-graph.md`. Format and commands TBD.

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
