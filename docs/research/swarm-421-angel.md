# security: follow-ups from #414 API-key default nits

Issue: https://github.com/brianreborn/familia/issues/421
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 06:13 PST
Approved-content-sha256: 732283f4800b886014464745a2f62c39c19fb016eeafde757af18e69fe2ec2df

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

### Issue Summary

The issue #421 is a follow-up from #414, which was approved with the hash `732283f4800b[number]a2f62c39c19fb016eeafde757af18e69fe2ec2df`. The follow-up focuses on security-related nits from #414, which were non-blocking on the reviews at the exact head commit `0c7e4effdb419eb9cef8b2873d2d423afa04b42c`.

### Proposed Approach

1. **Platform-Specific Issues:**
   - **0-byte-recovery delete race:** Implement a lock or an age check to prevent a race condition where a 0-byte file is deleted before it can be recovered.
   - **Windows unlink of an open file:** Ensure that an open file cannot be deleted on Windows. This can be achieved by using a file lock mechanism.
   - **Split test using str.split:** Modify the split test to use Windows-specific argument parsing rules instead of the generic `str.split`.
   - **Windows key-file ACL check:** Implement a check to ensure that the ACL (Access Control List) of a key file is correctly set on Windows.

2. **General Security Considerations:**
   - Review and update any security-related code to ensure it adheres to best practices and is secure against common vulnerabilities.

### Risks and Test Ideas

1. **0-byte-recovery delete race:** 
   - **Risk:** The race condition could lead to data loss

-- swarm/angel
