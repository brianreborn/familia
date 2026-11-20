# API-key file resolution failures on FreeBSD

Issue: https://github.com/brianreborn/familia/issues/592
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.7-live mode=live)
Generated: 2026-11-19 17:59 PST
Approved-content-sha256: 483addc7213f32b1df8a2ca44867316e7bfb1bf5f527f54a1e6c5c8a7502aae5

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18114); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=[user] role=swarm-pull prog=swarm-pull@0.2.7-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

<think>
</think><think>
</think>(a) **What the issue asks:**  
Issue #592 reports that on FreeBSD the test suite (`test_hermes_resolve.py`) fails with a `TypeError` because a helper function `fake_shebang()` is called with an unexpected keyword argument `'path_env'`. Additionally, the tests expect the API key file at `/tmp/pytest-of-green/.../.config/familia/api.key`, but on FreeBSD the script actually creates the key file under `~/.cache/familia/a57-ssh-ci.yaml`. The fix is to update the test helpers so they read the key from the correct path, derived from environment variables like `HOME` and `XDG_CONFIG_HOME`, and to use the proper helper functions (e.g., `get_home()`).

(b) **Proposed approach and likely components:**  
- Locate the test helper functions such as `get_home()` and `fake_shebang()`.  
- These helpers are probably used to build paths for environment variables and shell scripts.  
- The failing call `fake_shebang() got an unexpected keyword argument 'path_env'` suggests that the function signature in the code does not accept a `path_env` keyword, but the call passes it.  
- The expected location of the key file on FreeBSD is different from the old location. The code should derive the config directory from environment variables (`HOME`, `XDG_CONFIG_HOME`) rather than hard?coding paths.  
- Files/components involved:  
  - `test_hermes_resolve.py` (the test module containing the failing tests).  
  - Any shared test utilities or helper modules (e.g., `get_home.py`, `fake_shebang.py`, or similar) that define `fake_shebang()` and path resolution logic.  
  - Possibly the script that writes the API key file (`~/.cache/familia/a57-ssh-ci.yaml` on FreeBSD) and the environment that sets `HOME`/`XDG_CONFIG_HOME`.

(c) **Risks and test ideas:**  
- **Risks:**  
  - Changing path resolution logic may affect other platforms (e.g., Linux, macOS) where the old location is correct.  
  - The `fake_shebang()` function may be used elsewhere; altering its signature could break other tests.  
  - Environment variable handling on FreeBSD may differ; ensure the new helper respects `XDG_CONFIG_HOME` and `HOME`.  
- **Test ideas:**  
  - Add a test that asserts the expected key file path on FreeBSD matches the new derived path (e.g., check `~/.cache/familia/a57-ssh-ci.yaml`).  
  - Write a small integration test that runs the relevant test (`test_freebsd_ports_layout_preferred`, `test_freebsd_ignores_snap_path_strings`) and verifies that `api.key` is found at the correct location without raising `TypeError`.  
  - Verify that `get_home()` returns the correct `HOME` value on FreeBSD and that `XDG_CONFIG_HOME` is respected.  
  - Ensure the `fake_shebang()` call is updated to accept the new keyword argument (or remove the extra argument) and passes the appropriate `path_env` parameter.

(d) **Open questions:**  
- What is the current definition of `fake_shebang()` and its intended parameters?  
- How does FreeBSD configure `HOME` and `XDG_CONFIG_HOME`?  
- Is the path `~/.cache/familia/a57-ssh-ci.yaml` the correct location for the API key file on FreeBSD?  
- Are there other platforms where the key file location differs, and how should the code handle them?  
- Does the test suite have environment variables set for `HOME`/`XDG_CONFIG_HOME` on CI runners (e.g., Green CI)?

-- swarm/box
