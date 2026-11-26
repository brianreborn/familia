# hermes-escalation-config.sh execs a CWD-relative script

Issue: https://github.com/brianreborn/familia/issues/617
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-26 05:34 PST
Approved-content-sha256: 62f2c0b4cceea0968708cfa1d83cea3b29ab4da9e31c63e0c403a6ac11a33e7c

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18112); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

<think>
</think># Issue #617 ? First-pass work note (plain ASCII markdown)

## (a) What the issue asks

**Issue #617** reports a **security/scoping problem** in the file `scripts/hermes-escalation-config.sh`.  
When the script is executed, it runs `exec python3 scripts/hermes_modes.py`.  
The path to `scripts/hermes_modes.py` is **resolved relative to the current working directory (CWD)** at runtime, not relative to where the shell script itself lives.  

Consequences:

* If a user or agent sources or runs the script from a different directory, the relative path `scripts/hermes_modes.py` resolves to a different `hermes_modes.py` (or may fail).  
* The `-- HERMES-ARGS` flags are appended *after* the relative path, so when invoked as `./hermes-escalation-config.sh -- HERMES-ARGS ...` the flags end up pointing to the `hermes` executable instead of the intended caller.  

Thus the attacker model is **local** (a user or agent on the same machine) who can source or execute the file from an untrusted checkout or from an arbitrary CWD, potentially causing the wrong script to run and mis?direct the flags.

---

## (b) Proposed approach & likely involved files / components

**Goal:** Make the script locate `hermes-escalation-config.sh` and `hermes_modes.py` **relative to the script?s own location** (i.e., the directory that contains the script) rather than the current working directory.

**Steps to implement:**

1. **Resolve the script?s own path at the top of the file.**  
   - In bash, we can obtain the directory of the script that is being sourced or executed via:
     ```bash
     dir="$(cd "$(dirname "$0")" && pwd)"
     ```
   - Or, if the script is sourced (`source scripts/hermes-escalation-config.sh`), we can use the path of the sourcing file:
     ```bash
     dir="$(cd "$(dirname "$0")" && pwd)"
     ```
   - This gives the absolute path of the directory that contains `hermes-escalation-config.sh`.

2. **Build the path to `hermes_modes.py` from that directory** (and any other relative references inside the script) instead of relying on `$@` or CWD.

3. **Insert the flags before the caller?s arguments.**  
   - Currently the script does something like:
     ```bash
     exec python3 scripts/hermes_modes.py "$@"
     ```
   - Change to:
     ```bash
     exec python3 "$HERMES_MONTHS_DIR/scripts/hermes_modes.py" "$@"
     ```
   - Where `$HERMES_MONTHS_DIR` is derived from the script?s own location (e.g., `dirname "$0"`), or a variable set by the caller.

4. **Adjust flag placement.**  
   - The issue notes that flags are appended after `"$@"`. The fix is to place them **before** the caller?s arguments and before any `--` separator, so they reach the correct executable (`hermes` vs. the script).  
   - This can be done by constructing the command line array explicitly:
     ```bash
     CMD=(python3 "$SCRIPT_DIR/scripts/hermes_modes.py")
     # then add flags and args
     ```

**Files / components likely involved**

| Component | Reason |
|-----------|--------|
| `scripts/hermes-escalation-config.sh` | The script to fix. |
| `scripts/hermes_modes.py` | The script that gets executed; its path is relative to CWD. |
| `hermes` executable (or `hermes-*` binaries) | Flags (`-- HERMES-ARGS`) should be passed to `hermes`, not to the mode script. |
| Sourcing mechanism (e.g., `.sh` inclusion in other files) | Must also resolve paths relative to the sourcing file, not CWD. |

---

## (c) Risks and test ideas

### Risks

1. **Path resolution mistakes** ? Using `dirname "$0"` inside a sourced file can be tricky if `$0` changes after sourcing (e.g., when the file is sourced by another script). Need to verify that the resolved directory matches the location of `hermes-escalation-config.sh` and that `hermes_modes.py` exists there.
2. **Hard?coded relative paths** ? If any other relative paths inside `hermes-escalation-config.sh` (e.g., to config files) also rely on CWD, they may break.
3. **Permissions / symlinks** ? Resolving via `cd` to the script?s directory may follow symlinks; ensure the intended target is used.
4. **Interaction with environment variables** ? The maintainer mentions `HERMES_ACCEPT_LICENSES=1` stays default; ensure new path changes don?t affect that.

### Test ideas (unknown results ? outline)

1. **Copy the script to a different directory** and run it from that directory.  
   - Expected: `hermes_modes.py` should be found in the *new* directory, not the original one.  
   - Verify that `exec python3 ?` uses the correct script path and that flags are passed to `hermes`, not to the mode script.

2. **Source the script from an untrusted checkout** (e.g., `source /path/to/untrusted/hermes-escalation-config.sh`).  
   - Confirm that `$0` inside the script refers to the sourced file, and that `dirname "$0"` yields the correct directory.

3. **Run with explicit arguments** and check that `-- HERMES-ARGS` appears before the arguments.  
   - Example: `bash scripts/hermes-escalation-config.sh --foo bar`.  
   - After fix, the command line should be something like:  
     `python3 /abs/path/scripts/hermes_modes.py -- HERMES-ARGS foo bar` (or appropriate flag placement).

4. **Check behavior when invoked as `./hermes-escalation-config.sh` from its own location** ? ensure no double `--` or missing flags.

5. **Unit/integration test** ? Use a temporary directory, create a minimal `hermes_modes.py` in that directory, and run the fixed script from that temp dir.  
   - Verify exit code and that the mode script receives the right arguments.

---

## (d) Open questions

- **Exact current code**: What does the script currently contain around the `exec` line and flag handling? (Unknown ? need to inspect the file.)
- **How `hermes_modes.py` is invoked elsewhere**: Does it expect arguments that must be passed through? If so, the new ordering must preserve them.
- **Role of `HERMES_ACCEPT_LICENSES=1`**: Is this a variable set by the caller or part of the script? Need to confirm.
- **Sourcing vs. execution**: Should the fix apply to both direct execution (`./hermes-escalation-config.sh`) and sourcing (`source scripts/hermes-escalation-config.sh`)? The issue mentions ?untrusted checkout or CWD?, so both paths matter.
- **Potential side effects**: Changing path resolution might affect other scripts in the same directory; any relative paths inside `hermes-escalation-config.sh` should be reviewed for CWD dependence.

---

*Prepared as a first?pass note for GitHub issue #617.*

-- swarm/galaxy2
