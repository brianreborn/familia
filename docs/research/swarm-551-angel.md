# swarm-pull follow-ups from #550 reviews (Race A1-A3, Boundary info items)

Issue: https://github.com/brianreborn/familia/issues/551
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 05:10 PST
Approved-content-sha256: c20fe19f167f9c5a470ab3cc4bc035f4745534fe45c8af6fd572919fb3449259

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #551: Swarm Pull Follow-ups from #550 Reviews

### a. What the issue asks

The issue is to collect follow-up tasks from the exact-head approvals of #550, which were merged as part of PR 67b7ea2 and 0.2.6-live. The follow-ups address race conditions and boundary issues identified during the reviews.

### b. Proposed approach and files/components likely involved

1. **Race nits**:
   - Sweep stale temp files at home setup.
   - Delete the `.bak` temp file on error.
   - Ensure there is a directory `fsync` between renames in the atomic save path.

2. **Boundary info items**:
   - Address the TOCTOU window in the `islink`-then-read check on load and on the `.bak` copy.
   - Implement `getattr(os, "O_NOFOLLOW", 0)` to handle symlinks on platforms lacking the flag.
   - Clean up the bak temp file if the bak replace fails.

### c. Risks and test ideas

- **Race nits**:
  - Ensure that the `.bak` temp file is deleted on error.
  - Verify that the directory `fsync` is set between renames.

- **Boundary info items**:
  - Test the TOCTOU window to ensure it is properly handled.
  - Verify that `getattr(os, "O_NOFOLLOW", 0)` works as expected on different platforms.
  - Test the cleanup of the bak temp file to ensure it is handled correctly.

### d. Open questions

- **Race nits**:
  - Should the `.bak`

-- swarm/angel
