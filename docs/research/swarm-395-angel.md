# FreeBSD: test_windows Activate.ps1 UTF-8 BOM on host venv

Issue: https://github.com/brianreborn/familia/issues/395
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:18 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue Summary

The issue is related to the FreeBSD test suite for the familia project. The test `test_ps1_files_have_utf8_bom_for_windows_powershell_51` is failing on the FreeBSD 15.1 host due to the presence of a UTF-8 BOM in the `Activate.ps1` file within the host's virtual environment (venv). The BOM is not present in the repo-shipped Windows scripts, which is causing the test to fail.

## Proposed Approach

1. **Limit the Scan to Repo-Shipped Windows `.ps1` Paths**: Modify the test to only scan for `.ps1` files within the repo-shipped Windows directories (e.g., `scripts/windows/`, `install/windows/`) and exclude the host-created venv, `.venv`, `.cache`, and other generated trees.

2. **Do Not Rewrite the CI venv's `Activate.ps1`**: Ensure that the CI venv's `Activate.ps1` remains unchanged to avoid introducing unintended changes.

3. **Confirm the Repo-Shipped Scripts Still Have the BOM**: Run the test on the repo-shipped scripts to ensure that the BOM is present and that the test is correctly identifying it.

## Risks and Test Ideas

- **Regression on Other Platforms**: Ensure that the fix does not introduce any regressions on other platforms, particularly Linux CI.
- **Impact on Hot-Frozen Files**: Verify that the fix does not affect any hot-frozen files or FreeBSD/Termux documentation.
- **Testing on Multiple Environments**: Test the fix on multiple environments, including different FreeBSD versions and architectures, to ensure compatibility.

## Open Questions

- **Impact on Windows Users**:

-- swarm/angel
