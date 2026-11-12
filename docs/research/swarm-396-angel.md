# FreeBSD: run-familia-ci.sh reports PASS when pytest failed

Issue: https://github.com/brianreborn/familia/issues/396
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:23 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue Summary

The issue is related to the `run-familia-ci.sh` script on FreeBSD, which reports a PASS status even when the pytest tests fail. The script uses `tee` to capture the pytest output and set `START_HUMAN` without assigning it, which can lead to the summary being incorrect.

## Proposed Approach

1. **Modify the Script**: 
   - Run the pytest step with `set -o pipefail` to ensure that the exit status of `tee` is correctly captured.
   - Alternatively, rewrite the pytest step in bash to avoid the pipe and capture pytest's own status.
   - Set `START_HUMAN=$(date)` next to `START` to ensure the summary is accurate.

2. **Testing**:
   - Test the script on the angel GitHub runner with the development-based commit to ensure that the tests pass.
   - Verify that the same tests pass on Linux CI to ensure no regression.
   - Ensure no edits are made to hot-frozen files or FreeBSD/Termux docs.

## Risks

- **Script Breakage**: Modifying the script could potentially break other parts of the CI process.
- **Regression**: The script may introduce new regressions if not tested thoroughly.

## Test Ideas

- **Manual Testing**: Run the script on the angel GitHub runner and verify the output.
- **Automated Testing**: Write unit tests for the script to ensure it behaves as expected.
- **Regression Testing**: Test the script on Linux CI to ensure no regressions.

## Open Questions

- **Impact on Other CI Systems**: Will this fix affect other CI systems that use the same script?
- **Backward Compatibility**: Does this fix break compatibility with existing CI configurations?

-- swarm/angel
