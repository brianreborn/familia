# hermes-escalation-config.sh: exec in a sourced function kills the caller's shell; caller flags lose to env defaults (beyond #617)

Issue: https://github.com/brianreborn/familia/issues/625
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-27 18:33 PST
Approved-content-sha256: b187368bfee0444443c24c42435badd6568c7968ed47fa02bae510dde6056e98

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18080); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #625 ? hermes-escalation-config.sh

## (a) What the issue asks
The script `scripts/hermes-escalation-config.sh` contains an `exec` inside a function that is meant to be **sourced**.  
- The function ends with `exec python3 .../hermes_modes.py`. When the file is sourced in an interactive shell or an agent wrapper, calling the function runs `exec`, which replaces the current shell. Consequently the caller?s terminal (or tmux pane) closes as soon as hermes exits.  
- Explicit command?line flags passed to the script (e.g., `--light A`, `--no-escalate`) are lost: they are appended after `"$@"` and `hermes_modes.py` takes the last argument, so environment defaults (`HERMES_LIGHT_MODEL`, `HERMES_ESCALATE`, ?) override user?supplied flags.  
The fix for #617 (inserting flag handling before caller args) also resolves precedence, but this issue asks only for a regression test.

## (b) Proposed approach and affected files/components
- **Remove the `exec` inside the function.** Instead invoke `hermes_modes.py` as a child process and capture its exit status with `return $?`.  
  - Option A: keep the file purely sourced ? have it export variables (`HERMES_*`) and then run `python3 hermes_modes.py` via subprocess.  
  - Option B: ship a small wrapper script `scripts/hermes-escalated.sh` that does the exec, while keeping `hermes-escalation-config.sh` as a source?only file (exports only).  
- **Fix flag precedence.** Insert handling of environment variables and explicit flags *before* appending the caller?s arguments (`"$@"`). This ensures user?provided flags take priority over defaults.  
- **Update call sites** that previously relied on `exec` to avoid breaking scripts that expect the function to replace the current process.

**Likely files/components**
- `scripts/hermes-escalation-config.sh` ? main script (to be edited).  
- `hermes_modes.py` ? module invoked by exec; may need a different argument interface.  
- Environment variables: `HERMES_LIGHT_MODEL`, `HERMES_ESCALATE`, etc. (already defined elsewhere).  
- Possibly `~/.hermes/config/hermes-config.sh` for config export.

## (c) Risks and test ideas
**Risks**
- Removing `exec` may change the parent shell?s environment when sourcing; callers that expect the function to replace the current process could break.  
- Switching from an exec to a child process means we lose the direct return value of `hermes_modes.py`. Need to verify exit?status propagation (`return $?`).  
- Changing argument handling affects the order in which flags are passed; existing scripts that parse arguments after this file may need adjustment.

**Test idea (regression test)**
1. Create a stub `hermes_modes.py` in the current shell that prints its argv and exits with 0.  
2. Source `scripts/hermes-escalation-config.sh` inside a **subshell**:  

   ```bash
   bash -c 'source scripts/hermes-escalation-config.sh; echo $?'
   ```
3. Assert:
   - The subshell does **not** exit after sourcing (the shell stays alive).  
   - Running `hermes_modes.py` as a child produces the expected output.  
   - Explicit flags (`--light A`, `--no-escalate`) are passed correctly and override environment defaults. For example, set `HERMES_LIGHT_MODEL=B` and run `--light A`; after the fix `--light A` should still be used (or whichever precedence is desired).  
   - Subsequent commands executed in the same subshell continue to run.

## (d) Open questions
- Exact precedence order for environment variables vs command?line flags: does `HERMES_LIGHT_MODEL` take priority over a `--light` flag, or vice versa? The fix mentioned in #617 refers only to argument ordering.  
- How `hermes_modes.py` receives its arguments ? are they passed as positional values on the command line, via stdin/stdout, etc.?  
- Should the CWD?relative path handling from #617 be retained in this change? (Probably not needed for escalation config.)  
- Whether to keep a separate wrapper script (`hermes-escalated.sh`) and what its responsibilities are.  
- Impact on other scripts that source `hermes-escalation-config.sh` and rely on the current behavior of an exec.  

*Unknown specifics about exit?code propagation, argument parsing in `hermes_modes.py`, or environment variable precedence.*

-- swarm/galaxy2
