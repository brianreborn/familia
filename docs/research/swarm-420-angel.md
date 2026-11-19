# chore(tests): follow-ups from #417 test isolation nits

Issue: https://github.com/brianreborn/familia/issues/420
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:32 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #420: chore(tests): follow-ups from #417 test isolation nits

### What the issue asks

This issue is a follow-up from #417, which was a fix for #405. The goal is to address non-blocking issues related to test isolation in the familia project. These issues were discovered after the merge at ccb00b45be312a9a4e9902f278c6bc6e35a4c9b2.

### Proposed approach and files/components likely involved

1. **Platform-specific issues:**
   - **Windows:** The `import pwd` and `os.geteuid` functions break collection on Windows. This is because these functions are not available on Windows.
   - **Termux:** Capture the real HOME at import on Termux to ensure consistent behavior across platforms.
   - **child_python_env:** Ensure that `child_python_env` does not re-expose the user site from a venv, which can lead to incorrect test isolation.

2. **Testing.md wording:**
   - Update the wording in `TESTING.md` to include that `/private/tmp` is missing, which is a known issue on some platforms.

3. **Race conditions:**
   - Reap mock children before `rmtree` to prevent race conditions.
   - Optionally, add a stale sweep of `~/.cache/familia-pytest` on self-hosted runners to clean up any leftover files.
   - Ensure that the HOME vs USER_BASE assertion is always true, as this is a known issue.
   - Ensure that the child PYTHONPATH exports all of `sys.path

-- swarm/angel
