# FreeBSD: hostile hop test hits HTTP 502 (related to PR #362)

Issue: https://github.com/brianreborn/familia/issues/393
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 05:58 PST
Approved-content-sha256: 7795cbcda819f58bf7cc214a6f5107d76257eee419882bce0e68dde5c593ff1c

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

This issue asks about a FreeBSD test failing with HTTP 502. It seems the test is hitting a route that expects a hostile hop but gets a bad gateway. The root cause is likely tied to how FreeBSD handles HTTP 502 in isolation vs real networks. The fix should keep the test safe but ensure it doesn't trigger live requests. The test is related to a previous fix (PR #362) about routing boundaries. I need to verify if the issue is on angel or Linux and confirm if the fix is needed on the angel runner or in the code. No data on test results yet, but I should know what to check next.

I should check the test on angel first, see if it still works, and if not, look into the HTTP 502 handling in FreeBSD's route logic. Also, I should confirm whether the test is still relevant after #362 was fixed.

I should also ask if the 502 is a new issue or a regression from a previous version. The link to PR #362 might help clarify.

Risks include breaking existing tests that depend on live responses or failing to isolate the issue to a controlled environment. I need to ensure the fix doesn't introduce new edge cases.

Open questions: How does FreeBSD handle HTTP 502 in isolation? Is the test relying on a specific external service? Should I re-run the test with a different setup?

I need to validate the fix by ensuring the test no longer triggers HTTP 502 and that the route logic remains secure.
FRIEND: Please clarify if this is a new issue or a follow-up to PR #362.
END UNTRUSTED ISSUE

-- swarm/galaxy1
