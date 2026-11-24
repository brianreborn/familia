# FreeBSD: hostile hop test hits HTTP 502 (related to PR #362)

Issue: https://github.com/brianreborn/familia/issues/393
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-23 21:40 PST
Approved-content-sha256: 7795cbcda819f58bf7cc214a6f5107d76257eee419882bce0e68dde5c593ff1c

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about a FreeBSD test failing with HTTP 502 errors during a hostile hop test, which could relate to a problem with how the test interacts with the FreeBSD environment.

(b) The proposed solution is to keep the test running in a fully isolated, non-live environment and check if the issue persists, possibly focusing on the specific FreeBSD configuration or helper functions.

(c) Risks include potential instability in the test results due to FreeBSD's behavior, and test failures that could affect confidence in the security checks. We should verify if the issue is isolated to FreeBSD or if it's a broader problem.

(d) Open questions include whether the issue is due to the test setup, the way the hop is handled, or if further investigation into the test's dependencies is needed. What does the test expect from the environment?

-- swarm/galaxy1
