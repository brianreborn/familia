# hermes-escalation-config.sh execs a CWD-relative script

Issue: https://github.com/brianreborn/familia/issues/617
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:11 PST
Approved-content-sha256: 62f2c0b4cceea0968708cfa1d83cea3b29ab4da9e31c63e0c403a6ac11a33e7c

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18112); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

<think>
</think># Issue #617 ? First?pass work note (plain ASCII markdown)

## (a) What the issue asks

The file `scripts/hermes-escalation-config.sh` (a POSIX?style script) is executed by running `exec python3 scripts/hermes_modes.py`.  
The path to `scripts/hermes_modes.py` is **relative to the current working directory (CWD)**.  
If a user or agent sources or runs the script from a directory other than the one that contains it, the relative path resolves to a different `hermes_modes.py` (or may not exist at all).  
The fix should make the script locate its own location automatically and pass the extra flags (`-- HERMES-ARGS` etc.) **before** the caller?s arguments, rather than appending them after the caller?s `--` marker.

## (b) Proposed approach & likely involved files

- **Root cause file:** `scripts/hermes-escalation-config.sh` (the POSIX rewrite, touched by commit `ec08176`).
- **Target script:** `scripts/hermes_modes.py` (called via `exec python3 ?`).
- **Maintainer note:** `HERMES_ACCEPT_LICENSES=1` stays default; not part of this issue.

**Proposed changes**

1. **Resolve the script path from the file?s own location**  
   - Instead of relying on `$0` or `CWD`, compute the directory of the sourced script file itself.  
   - In a sourced/run context, `$0` points to the script that is being executed.  
   - Use something like:  

     ```bash
     SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
     SCRIPT_PATH="${SCRIPT_DIR}/hermes-escalation-config.sh"
     ```

   - Or, if the script is invoked via sourcing, capture the path of the file that was sourced and derive the directory from that.

2. **Insert the extra flags before the caller?s arguments**  
   - Currently the script appends flags after `"$@"`.  
   - Change to prepend them, e.g.:

     ```bash
     exec python3 "$SCRIPT_PATH" -- HERMES-ARGS "$@"
     ```

   - This ensures that any `--` that the caller supplies appears **after** the script?specific `--` flags, so the flags go to `hermes` (or the intended downstream tool) rather than being swallowed by the caller?s arguments.

3. **Update the shebang / POSIX rewrite** to use the above path resolution and flag ordering.

## (c) Risks & test ideas

| Risk | Why it matters | Mitigation / test |
|------|----------------|-------------------|
| **Breaking existing invocations** that already run from the correct directory | If a user runs the script from the same directory where `hermes_modes.py` lives, the new path resolution still yields the same file, so behavior should stay identical. | Run the script from the original directory and from a different one; compare output. |
| **Hard?coded relative path in other parts of the repo** | Fixing only this file may leave similar issues elsewhere. | Scan for other `exec ? scripts/?py` or `python3 scripts/?` calls that use relative paths. |
| **Interaction with `$0` in functions** (e.g., `source` or `eval`) | `$0` may not be the script file in all shells; deriving from the sourced file path is more reliable. | Write a small test that sources the script and then runs a child process; verify the child sees the correct script path. |
| **Flags ordering for `--`** | If the caller already passes `--` before their args, prepending `-- HERMES-ARGS` could shift arguments incorrectly. | Test with and without caller?supplied `--`. Use a simple invocation like `./hermes-escalation-config.sh --foo bar` and `./hermes-escalation-config.sh foo bar`. |
| **Portability across POSIX shells** | The script is POSIX?style; some shells may handle `$0` differently. | Ensure the fix uses only POSIX?compatible syntax (`$(cd ... && pwd)`). |

**Suggested minimal test suite (unknown results, just ideas)**

1. **Location test**  
   - `cd /tmp/other && bash scripts/hermes-escalation-config.sh` ? verify it runs `python3 scripts/hermes_modes.py` from `/tmp/other/scripts/` (or the directory containing `hermes_modes.py`).

2. **Flag order test**  
   - Run `bash scripts/hermes-escalation-config.sh -- HERMES-ARGS arg1 arg2` ? expect `-- HERMES-ARGS` to appear **before** `arg1 arg2` and the script to forward them to `hermes`.

3. **Sourcing test**  
   - `source scripts/hermes-escalation-config.sh` then `

-- swarm/galaxy2
