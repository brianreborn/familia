# Verify start.bat refuses --host/--port/--api-key argv overrides (F-6)

Issue: https://github.com/brianreborn/familia/issues/631
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:18 PST
Approved-content-sha256: a5015539807bfc369252a219f0ababef49645ccad4316f9bbd1433dba58a1314

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about ensuring that `start.bat` on Windows properly refuses any arguments that would cause it to behave unexpectedly, especially those that could override its own behavior. It highlights a need to verify how the script handles overrides and what environment variables control its operation.

(b) A likely approach would involve testing the behavior of `start.bat` with various arguments, checking logs for any unexpected outputs or exits, and confirming that it correctly prevents overrides from being passed through. The relevant files would be `scripts/windows/start.bat`, `scripts/bind_auth_guard.py`, and the environment variables `FAMILIA_BIND`, `FAMILIA_PORT`, and `FAMILIA_API_KEY_FILE`.

(c) Risks include potential misconfiguration of bind, port, or key settings, which could lead to incorrect connections or failures in the system. Testing should focus on ensuring the correct environment variables are set and that the script does not silently accept unwanted arguments.

(d) Open questions include how the system handles different configurations, whether the current setup aligns with expected behavior, and what additional checks are needed to fully validate the script's functionality.

-- swarm/galaxy1
