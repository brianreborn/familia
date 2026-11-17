# Fix the launch-only --tools limit (no v0.4.0 waiver)

Issue: https://github.com/brianreborn/familia/issues/630
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:21 PST
Approved-content-sha256: 794c6d0ffc529c9b22cbf3283b3dd74eb2d9b42a36dcd746e104496e46e5dc1d

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18199); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

### Issue #630: Fix the launch-only --tools limit (no v0.4.0 waiver)

**Description:**
The launch-only `--tools` limit must be fixed for v0.4.0 so that the setting persists across restart, rather than remaining a documented known issue. The issue is documented in #611, which includes a v0.4.0 waiver that `--tools` remains launch-only. However, this waiver is not accepted, and the launch-only `--tools` limit must be fixed for v0.4.0.

**Proposed Approach:**
1. **Review and Update Documentation:**
   - Update the documentation to reflect that the `--tools` limit is no longer launch-only and that it persists across restart.
   - Ensure that the documentation is clear and concise.

2. **Modify the Code:**
   - Modify the code to ensure that the `--tools` setting persists across restart.
   - This may involve changes to the configuration management system or the restart mechanism.

3. **Testing:**
   - Conduct thorough testing to ensure that the `--tools` setting persists across restart.
   - Test the system with various scenarios, including restarts, crashes, and hand-starts.

**Risks:**
- **Data Loss:** If the `--tools` setting does not persist across restart, it could lead to data loss or incorrect behavior.
- **Complexity:** Modifying the code to ensure that the `--tools` setting persists across restart could introduce complexity and potential bugs.

**Test Ideas:**
- **Restart Test:** Test the system after a restart to ensure that the `--tools` setting persists.
- **Crash Test

-- swarm/angel
