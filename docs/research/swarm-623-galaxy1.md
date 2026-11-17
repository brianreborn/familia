# scripts/watchdog_test.sh never times out

Issue: https://github.com/brianreborn/familia/issues/623
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:11 PST
Approved-content-sha256: 1c8c267c8fe883e6db28e05ac99d3abe35dbf16937ac0f95529155652621a17f

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about a script that isn't timing out properly. It seems the test script is stuck waiting for a process to finish without a proper timeout, which is causing it to hang.

(b) To fix this, the script should include a timeout mechanism, ensure arguments are quoted, and verify the command's output correctly. Likely components involved are the script itself, the watchdog process, and possibly a monitoring tool.

(c) Risks include the script failing to complete if the monitored process takes too long, and tests not accurately reflecting real behavior. Tests should confirm the timeout works and the script behaves as expected.

(d) Open questions include how the timeout is implemented, whether the process is truly being monitored, and how to validate the fix without breaking existing tests.

-- swarm/galaxy1
