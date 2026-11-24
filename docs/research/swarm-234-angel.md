# test: Windows/pwsh/man/groff tests always skipped on Linux

Issue: https://github.com/brianreborn/familia/issues/234
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 16:55 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

### Issue Summary

The issue is that the Windows-specific tests in the familia project are being skipped on Linux due to missing dependencies such as PowerShell (`pwsh`), `man`, and `groff`. The tests are marked with `pytest.mark.skipif(not shutil.which('pwsh'))` and similar checks, which prevent them from running on Linux systems where these dependencies are not installed.

### Proposed Approach

1. **Run Tests on Windows:**
   - Execute the tests on the `miryam` or `qodesh` machines, which have PowerShell installed, to ensure that the Windows-specific tests pass.
   - Report the results of these runs to confirm that the tests are working as expected on Windows.

2. **Consider Installing PowerShell in CI:**
   - Investigate the possibility of installing PowerShell in the CI environment to ensure that all tests, including the Windows-specific ones, are run consistently across different platforms.

### Risks

- **Test Coverage:** Running the tests on Windows might uncover issues specific to Windows that are not caught on Linux.
- **CI Stability:** Ensuring PowerShell is installed in the CI environment could introduce additional complexity and potential issues.

### Test Ideas

- **Manual Testing:** Perform manual testing on the `miryam` or `qodesh` machines to verify that the Windows-specific tests pass.
- **Automated Testing:** Set up a CI pipeline that includes running the Windows-specific tests on `miryam` or `qodesh` to ensure consistency.

### Open Questions

- **Dependency Management:** How can we ensure that all necessary dependencies are installed on Linux systems to run the tests?
- **CI Configuration:** What is the best way to configure the CI pipeline to include running

-- swarm/angel
