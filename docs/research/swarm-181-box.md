# Dedicated requirements: installer/bootstrap UI (scopes, dependency/elevation pop-ups, licenses, preflight, parity)

Issue: https://github.com/brianreborn/familia/issues/181
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:37 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

- U1: Install scopes: user (`~`, default), custom `--prefix`, global. Upgrade and
uninstall cleanly in every scope. (#178)
- U2: Download-then-run: named `install-<project>.sh` and `.ps1` files, never pipe-to-shell. (#178)
- U3: Dependency halt pop-up: missing dependencies, with Install, Copy command, Retry and Change location. (code-bootstraps #39)
- U4: Elevation warning pop-up: shown *before* a step that needs root/admin. No silent elevation; show what will be written. (code-bootstraps #39)
- U5: Licenses: each license prompted once per run, acceptance remembered. Unknown licenses get a flashing warning on the same prompt.
- U6: Live output and recovery: live start log, a recovery path when start-up fails, and model downloads in the background. Never a silent wait.
- U7: Up-front preflight: every dependency, disk and permission check runs before any long build or download.
- U8: Parity: the terminal banner and the cockpit pop-up carry the same information, and every prompt has a headless flag (`--yes`, `--auto-deps`).
- U9: Speed: fresh bootstrap time is measured and kept down. (code-bootstraps #40)
- U10: No raw git required: the user never has to use git's own interface to install, update or contribute. (#182)

**Done when:** the doc is merged, every section links an issue, and the swarm fresh-clone tests cover

-- swarm/box
