# Ensure lock file permissions and ownership on FreeBSD

Issue: https://github.com/brianreborn/familia/issues/596
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:29 PST
Approved-content-sha256: 9e8c1073849b15b15c797caa8d7f7b1ce12fe2e12a5de68f9994d0d1bc13c7ac

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18112); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #596 - FreeBSD lock file permissions and ownership

## (a) What the issue asks

The issue reports that the script creates a lock file at `~/.cache/familia-a57-ci.lock` with mode `0600`. On FreeBSD, it needs to verify that:

- The directory `~/.cache/familia-a57-ci.lock` exists and is owned by the runner user.
- The file itself has mode `0600`.
- If either the ownership or the mode is incorrect on FreeBSD, the issue asks to adjust them.

## (b) Proposed approach

**Approach:** After creating the lock file, run commands to check and fix ownership and permissions on FreeBSD. Specifically:

- Determine the current owner of the directory and file.
- Check the current mode of the file.
- If they differ from `owner:group:mode = <runner_user>:<some_group>:0600`, change them.

**Likely involved files/components:**

- The script that creates the lock file (not shown, but referenced as `familia-a57-ci.lock` under `~/.cache/`).
- FreeBSD `chown` and `chmod` commands or equivalent.
- Possibly the runner user account and its group membership.

## (c) Risks and test ideas

**Risks:**

- On FreeBSD, default permissions for directories and files may differ from Linux; e.g., `chmod 0600` may not be sufficient or may require `chown` first.
- The runner user may not exist or may have unexpected group ownership.
- The script may be run by different users; hardcoding the owner may break on other systems.
- The cache directory `~/.cache/` may already exist with different ownership/permissions; the script should handle or overwrite correctly.

**Test ideas (unknown specifics, but general):**

- Run the script on a FreeBSD machine and inspect `stat` output for the lock file after execution.
- Check `ls -l` in `~/.cache/` and the file itself.
- Verify that `chown` and `chmod` commands succeed without errors.
- Test with a different runner user to see if the fix is portable.

## (d) Open questions

- What is the name of the runner user? (Not specified in the issue.)
- What group should the lock file belong to? (Not specified.)
- Is the script already run on FreeBSD? If so, what was the previous state?
- How is the script invoked? (Not provided.)
- Does the `familia-a57-ci.lock` path change per run? (The name includes `a57`, suggesting a version or config.)

Unknown measurements: current owner, group, mode, existence of directory, script location, etc.

-- swarm/galaxy2
