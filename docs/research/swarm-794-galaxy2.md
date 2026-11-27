# 0.5.0 FreeBSD CI: preserve failure exit status

Issue: https://github.com/brianreborn/familia/issues/794
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-27 14:45 PST
Approved-content-sha256: ee4954f4e97def8a15f6cb3915178bf94e22e7d0c5630493470b9587d342fdae

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18080); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #794 ? 0.5.0 FreeBSD CI: preserve failure exit status

## (a) What the issue asks
The FreeBSD CI workflow for version?0.5.0 (`run-familia-ci.sh` and any related entrypoints) currently reports **PASS** even when one of the required commands fails.  
We need to audit those scripts, make sure each required command?s exit status is propagated to the overall job, and ensure that a deliberately failing command makes the CI run exit non?zero while still indicating which step failed. The fix should be narrow (only touch the parts needed) and not duplicate work already done in PR?#396.

## (b) Proposed approach & files/components
- **Locate the target script(s).**  
  - Primary candidate: `run-familia-ci.sh` (root of the repo or a scripts/ directory).  
  - FreeBSD?specific entrypoints may live in `.github/workflows/ci.yml`, local Makefiles, or CI config files ? unknown without inspecting the repo.  

- **Identify required commands.**  
  - List every command that is expected to run as part of the test suite (e.g., linting steps, dependency checks). These are the ?required? ones whose exit status must be preserved.

- **Wrap each command so its status is captured and passed through.**  
  A minimal pattern for a single command could be:

    ```sh
    result=$?
    "$@" >/dev/null 2>&1 || { echo "FAILED: $* (exit $result)" >&2; }
    exit $result
    ```

  - For pipelines, enable `set -o pipefail` and run each pipeline step in a subshell that captures `$?`.  
  - Add a cleanup trap after each major block to reset environment variables or temporary files.

- **Check existing #396 PR coverage.**  
  - If the previous PR already added wrappers for some commands, verify which ones are missing. Only add new wrappers where not yet present; avoid duplicating logic.

- **Preserve overall exit status.**  
  - At the end of `run-familia-ci.sh`, explicitly `exit $?` (or propagate the last captured status) so the CI entrypoint returns non?zero when any required command fails.

## (c) Risks & test ideas
| Risk | Mitigation |
|------|------------|
| Changing global flags (`set -e`, `pipefail`) may affect unrelated steps. | Run the script locally with a known good set of commands first; then add failing ones one by one and re?run to confirm exit code flips from 0 ? 1. |
| FreeBSD?s default shell handling differs (no built?in pipefail). | Explicitly enable `set -o pipefail` inside the script or use Bash's `-e` after each command invocation. |
| Environment variables set by CI may be lost if cleanup is too aggressive. | Keep a minimal trap that only restores paths/flags needed for subsequent commands; avoid deleting them entirely. |

**Test ideas**
1. **Passing case:** Run the script with all required commands succeeding. Verify it exits 0 and prints ?PASS? or similar.
2. **Failing case:** Insert a deliberately broken command (e.g., `false` or a non?existent binary) at the top of `run-familia-ci.sh`. Confirm the overall exit status becomes non?zero and that the failure message mentions the offending step.

## (d) Open questions
- **What exactly does PR?#396 cover?** (e.g., which commands are already wrapped?) ? *unknown* from the issue text.  
- **Are there additional entrypoints or workflow files for FreeBSD besides `run-familia-ci.sh`?** ? *unknown*.  
- **How is failure reporting currently displayed?** Should we add a specific ?failed step? line, or rely on existing output?  
- **Host?specific paths / private addresses:** Which directories or variables should be excluded from the patch to avoid committing them?

*Prepared as a first?pass note; file contents and exact command lists are unknown until inspected.*

-- swarm/galaxy2
