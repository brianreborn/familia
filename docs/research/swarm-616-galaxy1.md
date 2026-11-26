# swarm-pull: validate_draft (#580) is never called; model drafts still reach PRs unchecked

Issue: https://github.com/brianreborn/familia/issues/616
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-26 07:36 PST
Approved-content-sha256: d11f9e3c2c77bb5501c6857b16786fd3e5957d7de06c3417a2531e4ce869b7b4

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

<think>
</think># Issue #616: swarm-pull: validate_draft is never called

## (a) What the issue asks

The issue reports that `validate_draft()` was added to `scripts/swarm/swarm-pull` (commit `83e7562`), but the job function `job()` never calls it. The code path still goes through `model_draft` ? `draft.md` ? `build_doc` ? `deliver`. Because the protection (the call to `validate_draft`) is dead code, an attacker could craft a local model prompt that leaks the nonce or output into a public pull request body (e.g., via prompt echo, nonce or fence leakage, or truncated output). The fix is to actually invoke `validate_draft(draft, nonce)` right after `model_draft` returns, initialize the nonce on both prompt branches, fail closed on `ForgeError`, match markers case-insensitively, replace non-ASCII in comments, and add a job-level test asserting that a draft containing the nonce never reaches `deliver()`.

## (b) Proposed approach and files/components

- **File to modify:** `scripts/swarm/swarm-pull` (the file containing `job()` and the `swarm-pull` script).  
- **Component to change:** The flow after `model_draft` returns. Instead of going straight to writing `draft.md` and then `build_doc` and `deliver`, insert a call to `validate_draft(draft, nonce)` immediately after `model_draft` completes.  
- **Nonce handling:** Ensure `nonce` is initialized on both prompt branches (the two places where the prompt is generated).  
- **Error handling:** On `ForgeError`, make the process fail closed: no push, no PR. Only allow the ?probe-only? note.  
- **Marker matching:** Make marker matching case-insensitive.  
- **Comments:** Replace non-ASCII characters in comments (lines 2534?2552) with ASCII equivalents.  
- **Test addition:** Add a job-level test (e.g., in the test suite for `swarm-pull`) that builds a draft containing the nonce and asserts that `deliver()` is never called for that draft.

## (c) Risks and test ideas

- **Risk:** Introducing a call to `validate_draft` may change the order of operations or introduce new side effects (e.g., validation might need data not yet available). Must ensure the call does not break existing flow for normal drafts.  
- **Risk:** Failing closed on `ForgeError` could prevent legitimate deliveries if `ForgeError` is expected in some cases. Need to verify that `ForgeError` is only raised for probe-only scenarios.  
- **Risk:** Case-insensitive marker matching could affect existing behavior; need to audit all marker usages.  
- **Test ideas (unknown specifics, but plausible):**
  - Add a unit test in the job test harness: create a draft string that includes the current nonce value; assert that `deliver()` is not invoked for that draft.  
  - Write an integration test that runs `swarm-pull` with a prompt that contains the nonce and inspect the PR body to ensure no nonce leak or echo.  
  - Verify that on `ForgeError`, the script exits without pushing a commit or creating a PR.  
  - Run the existing test suite for `swarm-pull` to ensure no regressions.  
  - Check that non-ASCII characters in comments are replaced and that the diff matches the expected change.

## (d) Open questions

- What exactly triggers `ForgeError`? Is it expected only for probe-only notes?  
- How is the `nonce` initialized for each prompt branch? Where is the variable defined?  
- What is the exact signature of `validate_draft(draft, nonce)` and what does it return/do?  
- Where in `swarm-pull` is `model_draft` called, and what is the return value?  
- How are markers matched case-insensitively?does this affect other parts of the codebase?  
- What is the current behavior of `deliver()` for drafts that contain the nonce?  
- Are there other callers of `validate_draft` in the repository that might need updating?  
- What is the impact on the ?probe-only note? allowed behavior?

-- swarm/galaxy1
