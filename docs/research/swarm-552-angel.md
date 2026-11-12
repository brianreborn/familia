# v0.3.0 release 1/4: smoke-test main on primary Unix platforms

Issue: https://github.com/brianreborn/familia/issues/552
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 05:15 PST
Approved-content-sha256: 7c3138d99b2f69eb1d04ad976d767500698ea3ff706e495f8857354ca5ede9e1

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

### Issue Summary

The issue asks for a smoke-test of the current main branch on primary Unix platforms: Linux (box, miryam), FreeBSD (angel), and Android Termux (galaxy1, galaxy2 when sshd is back). The smoke test should be a quick, non-persistent install and launch of the main branch on each reachable primary platform. The results should be posted as a pass/fail table per host as a comment, and any install/run blockers should be filed as their own issue labeled `release-blocker`.

### Proposed Approach

1. **Set Up Test Environment**: Ensure that all necessary test environments are set up for each platform.
2. **Run Smoke Test**: Install and launch the main branch on each platform.
3. **Document Results**: Post a pass/fail table per host as a comment.
4. **File Blockers**: If any issues arise, file them as their own issue labeled `release-blocker`.

### Files or Components Involved

- **Test Scripts**: Scripts to automate the installation and launch process on each platform.
- **Smoke Test Results**: A table to record the pass/fail status of each platform.
- **Release Blocker Issues**: Issues to track any issues that prevent the release from proceeding.

### Risks

- **Platform Compatibility**: Ensuring that the main branch works correctly on all platforms.
- **Resource Usage**: Ensuring that the smoke test does not consume excessive resources.
- **Network Issues**: Ensuring that there are no network issues that affect the test.

### Test Ideas

- **Automated Testing**: Use automated scripts to perform the smoke test.
- **Manual Testing**: Conduct manual testing to ensure that the smoke test is accurate.

### Open Questions

- Real smoke-test execution across primary Unix platforms (Linux: box, miryam; FreeBSD: angel; Android Termux: galaxy1, galaxy2) is required before this issue can be considered verified for the v0.3.0 release.
- Per-host execution tracking: host, OS/arch, pin SHA, test command, PASS/FAIL status, and test log path.

-- swarm/angel
