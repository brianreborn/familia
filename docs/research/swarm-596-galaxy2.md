# Ensure lock file permissions and ownership on FreeBSD

Issue: https://github.com/brianreborn/familia/issues/596
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.2-live mode=live)
Generated: 2026-11-22 22:13 PST
Approved-content-sha256: 9e8c1073849b15b15c797caa8d7f7b1ce12fe2e12a5de68f9994d0d1bc13c7ac

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18112); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.2-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #596 - FreeBSD lock file permissions and ownership

## (a) What the issue asks

The issue reports that the script `familia-a57-ci` (or similar) creates a lock file at `~/.cache/familia-a57-ci.lock` with mode `0600`. On FreeBSD, it wants to verify that:

- The directory `~/.cache/familia-a57-ci.lock` exists and is owned by the runner user.
- The file itself has mode `0600`.
- If ownership or mode is not correct on FreeBSD, the issue asks to adjust ownership or set the mode accordingly.

So essentially, we need to ensure the lock file's permissions and owner match the expected defaults for the runner user on FreeBSD.

## (b) Proposed approach and components involved

**Proposed approach**

1. After creating the lock file, run commands to check and fix permissions and ownership on FreeBSD.
2. Use standard FreeBSD tools like `stat`, `chown`, `chmod` (or equivalent via `coreutils`/`busybox`).
3. Identify the "runner user" ? likely the user under which the script runs (e.g., the CI runner's username). We can find it via `whoami` or environment variables.

**Files / components likely involved**

- The script that creates the lock file (probably in the `familia` project, maybe `familia-a57-ci` or similar).
- The target directory: `~/.cache/familia-a57-ci.lock` (or similar path).
- Ownership and mode settings: `chown` and `chmod`.
- FreeBSD-specific commands: `stat -c %a` for mode, `stat -p` for owner/group, `chown`, `chmod`.

We don't have the script content, so we cannot name the exact script file, but it's likely a shell script in the `familia` repo.

## (c) Risks and test ideas

**Risks**

- On FreeBSD, default user may differ from Linux; assuming wrong user could cause ownership mismatch.
- Permissions may be set differently by the script; we must not break existing behavior on other systems.
- FreeBSD's `chmod` and `chown` syntax is similar to Linux but some paths may differ (`~/` vs `/home/user`).
- If the script runs as root, ownership may already be root; but "runner user" implies a non-root user.
- The lock file path may contain a versioned name (`familia-a57-ci.lock`); ensure the directory `~/.cache/` exists and is writable.

**Test ideas**

- Run the script on a FreeBSD runner and then check:

  ```bash
  id -u   # should match expected runner user
  stat -c "%a %U:%G %n" ~/.cache/familia-a57-ci.lock
  ```

- Verify mode is `600` (i.e., `rw-------`) and owner is the runner user.

- If not, run:

  ```bash
  chown <runner_user>:<runner_group> ~/.cache/familia-a57-ci.lock
  chmod 600 ~/.cache/familia-a57-ci.lock
  ```

- For CI environments, also check that the directory `~/.cache/` is owned by the user and has appropriate permissions.

- Since we don't have actual results, we say "unknown" for current state.

## (d) Open questions

- What is the exact path and script name that creates the lock file? (e.g., `familia-a57-ci` script, or part of CI workflow?)
- What is the "runner user" on FreeBSD? (Is it a specific username like `runner` or the CI service account?)
- Does the script already set ownership/mode, or only sets them later?
- Is there a group ownership for the cache directory? (FreeBSD default may differ.)
- Are there other similar lock files for other CI jobs? Should we handle them all at once?
- How does the script handle the case when the file already exists? (Overwrite? Rename?)

We do not have measurements or file contents, so we mark unknown where needed.

-- swarm/galaxy2
