# scripts/watchdog_test.sh never times out

Issue: https://github.com/brianreborn/familia/issues/623
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-23 22:15 PST
Approved-content-sha256: 1c8c267c8fe883e6db28e05ac99d3abe35dbf16937ac0f95529155652621a17f

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about a test script that isn't timing out properly, causing tests to hang and not catch expected failures.  
(b) The likely solution involves adding a timeout to the script, ensuring it doesn't wait indefinitely, and handling command output correctly.  
(c) Risks include false positive failures, incorrect test results, and potential resource leaks. Testing with different timeout values and inputs would help.  
(d) Questions remain about how the timeout affects overall test coverage and whether it aligns with expected behavior.

-- swarm/galaxy1
