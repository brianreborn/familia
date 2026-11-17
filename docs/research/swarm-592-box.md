# API-key file resolution failures on FreeBSD

Issue: https://github.com/brianreborn/familia/issues/592
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:35 PST
Approved-content-sha256: 483addc7213f32b1df8a2ca44867316e7bfb1bf5f527f54a1e6c5c8a7502aae5

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18114); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

<think>
</think><think>
</think>(a) **What the issue asks:**  
On FreeBSD, the test suite for `familia` (specifically `test_hermes_resolve.py` tests like `test_freebsd_ports_layout_preferred` and `test_freebsd_ignores_snap_path_strings`) fails because a helper function `fake_shebang()` is called with an unexpected keyword argument `path_env`. Additionally, the tests expect the API key file at `/tmp/pytest-of-green/.../.config/familia/api.key`, but on FreeBSD the script actually creates the key file under `~/.cache/familia/a57-ssh-ci.yaml`. The fix is to update the test helpers so they read the key from the correct path, derived from environment variables such as `HOME` and `XDG_CONFIG_HOME`, and to use the proper helper functions (e.g., `get_home()`).

(b) **Proposed approach and likely involved files/components:**  
- Locate the test helper functions, notably `fake_shebang()` and any path?resolution helpers such as `get_home()`.  
- Identify where the expected key file path (`/tmp/pytest-of-green/.../.config/familia/api.key`) is constructed in the test code or the environment setup.  
- On FreeBSD, the script writes the key to `~/.cache/familia/a57-ssh-ci.yaml` instead of the old `.config/familia/api.key` location.  
- Modify the helpers to derive the correct home directory from environment variables (`HOME`, `XDG_CONFIG_HOME`) and to call `fake_shebang()` with the appropriate `path_env` argument (or remove the extra argument if the signature changed).  
- Update the test assertions to look for the key file at `~/.cache/familia/a57-ssh-ci.yaml` (or the equivalent FreeBSD path) rather than the old location.  
- Files likely involved:  
  - `test_hermes_resolve.py` (or the module containing the failing tests).  
  - Any shared test utilities or helper modules (e.g., `get_home.py`, `fake_shebang.py`).  
  - Possibly the script that generates the key file on FreeBSD (the one referenced as `~/.cache/familia/a57-ssh-ci.yaml`).  

(c) **Risks and test ideas:**  
- **Risk:** Changing the path derivation could affect other platforms (Linux, macOS) where the key file location differs. Must ensure the new logic respects the existing behavior on those platforms.  
- **Risk:** If the environment variables `HOME` or `XDG_CONFIG_HOME` are not set correctly on FreeBSD, the derived path may still be wrong.  
- **Test ideas:**  
  - Add a dedicated test on FreeBSD that checks the actual file location of the key file after running the relevant script.  
  - Verify that `fake_shebang()` is called with the correct keyword arguments on FreeBSD (e.g., `path_env=...`).  
  - Run the failing tests after the change and confirm they pass on FreeBSD.  
  - Write a small script to print `get_home()` output on FreeBSD to validate environment variable handling.  
  - Ensure the test suite does not hard?code the old path; use `os.path.expanduser("~/.cache/familia/a57-ssh-ci.yaml")` or similar derived paths.  

(d) **Open questions:**  
- What exactly does `fake_shebang()` expect for the `path_env` argument? Is it a new parameter or was it renamed?  
- On FreeBSD, is the key file path `~/.cache/familia/a57-ssh-ci.yaml` the canonical location, or is there a different naming convention?  
- How is `XDG_CONFIG_HOME` defined on FreeBSD? Is it set by the default environment or needs to be overridden?  
- Does the test framework (pytest) run the script with the same environment on FreeBSD, and does it preserve `HOME` correctly?  
- Are there other platforms where the key file location differs, and should the fix be

-- swarm/box
