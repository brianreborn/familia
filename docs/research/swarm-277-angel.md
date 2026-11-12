# Handoff 1/8 (Team A ? Team B): ALPHA unattended install on all platforms, license gate

Issue: https://github.com/brianreborn/familia/issues/277
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:54 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #277: Handoff 1/8 (Team A ? Team B): ALPHA unattended install on all platforms, license gate

### Issue Summary
The goal is to implement an unattended install process for the Familia project on all supported platforms, including Linux, macOS, FreeBSD, Termux, and Windows. The license acceptance process should be controlled by various flags and should be validated through tests.

### Proposed Approach
1. **Create a new branch**: Start a fresh branch from the current `main` branch.
2. **Update platform matrix**: Use the Platform Reviewer's matrix to ensure all platforms are covered.
3. **Implement license gate**:
   - Split the `--yes` logic to ensure license acceptance in all entry points.
   - Gate dependencies and gum installs on the `license` variable.
   - Implement silent bypass for specific scripts.
   - Ensure `deps.ps1` passes winget `--accept-package-agreements` under `-Yes`.
4. **Update `install.sh` contribution notice**: Make it print-only or covered by `--yes`.
5. **Update tests**: Ensure all changes are covered by tests.

### Files and Components Involved
- `release-unattended-install-[number].md`: Platform matrix.
- `install.sh`, `install/linux/install.sh`, `install/termux/install.sh`, `install/windows/install.ps1`: Unattended install logic.
- `scripts/licenses.py`: License acceptance logic.
- `scripts/prefetch-first-models.sh`, `windows/prefetch-first-models.ps1`: Silent bypass logic.
- `deps.ps1`: Winget license acceptance logic.
- `tests`: Test cases for all changes.

### Risks

-- swarm/angel
