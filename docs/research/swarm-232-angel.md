# test: start.sh --yes times out in screen session-mode tests

Issue: https://github.com/brianreborn/familia/issues/232
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 16:51 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

### Issue Description
The issue involves a test in the `familia` project that is failing with a `subprocess.TimeoutExpired` error when running `start.sh --yes` in a screen session mode test. The test is part of the `test_start.py` file and is specifically for the `screen-*` cases. The failure is not visible in CI because the suite is never run in CI, and the error is ignored.

### Proposed Approach
1. **Modify `start.sh` to Fail Fast if `screen` is Missing:**
   - Add a check at the beginning of `start.sh` to verify if `screen` is installed. If not, the script should exit with a non-zero status, causing the test to fail fast.

2. **Re-run Tests on a Host with `screen`:**
   - Ensure that the CI environment has `screen` installed to avoid the timeout issue.

### Files and Components Involved
- `start.sh`: The script that is failing due to the timeout.
- `test_start.py`: The test file containing the `test_screen_session_mode_is_explicit_and_named` test.
- `.github/workflows/lint-warnings.yml`: The CI workflow that runs `pytest --collect-only`.
- `.ci/lint-warnings.sh`: The script that runs `pytest --collect-only`.

### Risks and Test Ideas
- **Risk of Missing `screen`:** Ensure that the CI environment has `screen` installed to prevent the timeout issue.
- **Test Idea:** Add a test case that explicitly checks the presence of `screen` before running the `start.sh` script. This can be done by using a shell script that checks for the presence of `screen`

-- swarm/angel
