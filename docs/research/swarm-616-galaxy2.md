# swarm-pull: validate_draft (#580) is never called; model drafts still reach PRs unchecked

Issue: https://github.com/brianreborn/familia/issues/616
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-26 07:41 PST
Approved-content-sha256: d11f9e3c2c77bb5501c6857b16786fd3e5957d7de06c3417a2531e4ce869b7b4

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18112); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

<think>
</think># Issue #616: swarm-pull: validate_draft (#580) is never called; model drafts still reach PRs unchecked

## (a) What the issue asks

The issue reports that `validate_draft()` was added to `scripts/swarm/swarm-pull` (commit `83e7562`), but the `job()` function never calls it. Drafts still go through the path `model_draft` ? `draft.md` ? `build_doc` ? `deliver`, and these unchecked drafts can still be pushed to a PR. An attacker (remote) could influence the model output, which then appears in the public PR body. This could lead to prompt echo, nonce or fence leakage, or truncated output. The issue author's text is inside a fenced block, but that fenced text itself can steer a local model whose output ends up in a public PR. The fix should ensure `validate_draft(draft, nonce)` is invoked right after `model_draft` returns, before any of the downstream steps, and that the nonce is initialized on both prompt branches. Also, on a `ForgeError` we should fail closed (no push, no PR) and only allow the probe-only note.

## (b) Proposed approach and likely files/components

**Proposed change**

1. In `scripts/swarm/swarm-pull` (or the file referenced by `:2525 on main 26d9720`), locate the `job()` function.
2. After `model_draft(...)` returns (i.e., after the model draft is produced), call `validate_draft(draft, nonce)` immediately.
3. Ensure `nonce` is initialized for both prompt branches (the two branches that handle the prompt).
4. In the error path (`ForgeError`), make the code fail closed: skip the push and PR steps; only emit the probe-only note.
5. Make marker matching case?insensitive.
6. Replace non?ASCII characters in comments (lines `:2534-2552`).
7. Add a unit/integration test at the `job()` level asserting that a draft containing the nonce never reaches `deliver()`.

**Files / components likely involved**

- `scripts/swarm/swarm-pull` (the file containing `job()` and the `model_draft` call).
- The `validate_draft()` function (already exists, but needs to be invoked correctly).
- Any code that writes `draft.md`, `build_doc`, and `deliver()` (the downstream steps).
- Possibly a test file for the swarm pull job (e.g., `test_swarm_pull_job.py` or similar) where the new assertion can be added.

## (c) Risks and test ideas

**Risks**

- Introducing a call to `validate_draft` may change the order of operations; ensure that side effects (e.g., writing files) are still correct.
- If `validate_draft` raises an exception for a valid draft, the job might abort before `deliver()` runs, which is the desired ?fail closed? behavior.
- The nonce initialization must happen before `validate_draft` is called; otherwise the check may be invalid.
- Case?insensitive marker matching could affect existing behavior; verify that it doesn?t break other parts.
- Replacing non?ASCII in comments is low risk but must be done correctly to keep linting/formatting.

**Test ideas (unknown specifics, but high?level)**

- Add a test in the job test suite that creates a draft containing the nonce and asserts that `job()` does **not** call `deliver()` and that `draft.md` is written (or whatever the expected artifact is) before `deliver()`.
- Verify that when `validate_draft` returns `True` for a draft that includes the nonce, the subsequent steps (e.g., `draft.md` write) still occur.
- Simulate a `ForgeError` and confirm that the job fails closed: no push to PR, no delivery, only the probe note is emitted.
- Check that both prompt branches (the ones referenced by the `:2534-2552` non?ASCII comment region) initialize `nonce` correctly.
- Run the existing test suite for `swarm-pull` to ensure no regressions.

## (d) Open questions

- Exact location of the `model_draft` call and where `job()` currently sits (the line numbers `:2953`, `:2954-2970` are given but not the file path).
- How `validate_draft` is defined and what it expects for arguments (`draft`, `nonce`).
- Whether `nonce` is already initialized elsewhere or needs to be created in the new code.
- The exact semantics of ?fail closed? on `ForgeError` (e.g., should it skip writing `draft.md` or just the push?).
- Whether case?insensitive marker matching should affect all marker comparisons in the file.
- The test file name and how to import the job for testing (unknown).
- Whether any other callers of `deliver()` need to be aware that drafts now go through `validate_draft` first.

-- swarm/galaxy2
