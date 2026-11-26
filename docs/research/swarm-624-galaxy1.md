# swarm-pull #580 gaps beyond #616: truncation check, reject/release/backoff path, preamble and fence coverage

Issue: https://github.com/brianreborn/familia/issues/624
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-26 05:11 PST
Approved-content-sha256: c74e7eff1c6d7e6e08ae15ddf81227a5a1a1f68f56620d043d7fbfab1d531b6a

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

[Issue #624] swarm-pull #580 gaps beyond #616

** (a) What the issue asks**

Issue #580 defines acceptance criteria for a ?swarm? job that includes several pieces of validation around drafts. #616 already covers some of those (fail?closed delivery, boundary D1) but leaves three gaps for the *swarm?pull* code in `scripts/swarm/swarm-pull`:

1. **Truncation check** ? `model_http` (lines?:2456?:2484) currently returns only `choices[0].message.content` and drops `finish_reason`. The CLI path has no stop signal. A draft that is cut off at `max_tokens` passes `validate_draft` as long as it is over 200 characters and has balanced fences.  
   *Fix*: make `model_http` return `(text, finish_reason)` and reject on ?length?. For the CLI path, reject when the generated token count reaches or exceeds `max_tokens`.

2. **Reject path / liveness loop** ? When #616 makes validation raise a `ForgeError`, the run loop?s generic handler (:3420) logs, sleeps (`retry`) and keeps the claim. The next iteration re?runs the probe and the model on the same issue until `HoldExhausted`. The re?running runner keeps the issue, burns model time and API budget, and no other runner can pick it up.  
   *Fix*: introduce a dedicated exception class `DraftRejected(ForgeError)` with a reason class (`nonce|fence|preamble|unbalanced|truncated|short`). Write `work/draft.rejected.md`. In the loop handle it like `NotApproved`: `release_issue(repo, n, "draft rejected: <class>", claim=claim)`, clear state, and enforce a per?issue cooldown (e.g. 6?h, doubling, capped at 48?h) that `pick_next()` / `candidate_issues()` respect.

3. **Preamble detection** ? The current detection only matches the start of the preamble (?You are ??). The exact matching rule is incomplete; the issue is cut off here.  
   *Fix*: extend the preamble regex / check to cover the full expected text.

** (b) Proposed approach**

- **File: `scripts/swarm/swarm-pull/swarm-pull.py` (or equivalent)**  
  - In `model_http` (the HTTP client that returns draft content): return a tuple `(text, finish_reason)` instead of just `text`.  
  - Add a token?count check before returning: if `len(generated_tokens) >= max_tokens` raise a new `DraftRejected` (or equivalent) with reason `truncated`/`short`.  
  - For the CLI entry point, after generating the draft, reject when token count ? `max_tokens` and emit a signal to the caller (e.g., `sys.exit(1)` or raise `DraftRejected`).

- **New exception class** ? `class DraftRejected(ForgeError):` with a `reason` attribute chosen from the allowed reason classes. Add a `work/draft.rejected.md` file template (to be authored) describing the rejection reason.

- **Cooldown logic** ? Introduce a per?issue attribute (e.g., `cooldown_hours = 0`) in the issue state. When a draft is rejected, set `cooldown_hours += step` (starting at 6?h, doubling each retry, capped at 48?h). `pick_next()` / `candidate_issues()` should skip issues whose `cooldown_hours > 0` and reset it after a successful pick.

- **Loop handling** ? In the run loop?s generic handler (:3420) replace the ?log, sleep, keep claim? behavior with a `except DraftRejected as e:` block that calls `release_issue(repo, n, f"draft rejected: {e.reason}", claim=claim)`, clears the issue state, and records the cooldown. Then re?probe the next candidate.

- **Preamble detection** ? Extend the existing preamble regex (or string check) to match the full expected opening line, e.g.:

  ```
  ^You are
  (?:started|launching|initiating|?)
  ```

  or simply match the whole phrase ?You are ?? up to a period. Update the code that calls `detect_preamble()` accordingly.

** (c) Risks and test ideas**

| Risk | Why it matters | Suggested test |
|------|----------------|----------------|
| **Breaking existing draft flow** | Changing `model_http` return signature may affect callers. | Unit?test `model_http` with a mock response; verify it now returns `(text, finish_reason)`. |
| **Token?count estimation** | `generated_tokens` may be inaccurate or not reflect final output. | Mock `model_http` to return a known token count; assert that `DraftRejected` is raised when `>= max_tokens`. |
| **Cooldown enforcement** | If cooldown is too short/long, it can cause starvation or excessive delays. | Write integration tests that create multiple draft issues, run the pick loop, and verify that after each rejection the next pick skips the same issue for the required period. |
| **Liveness loop elimination** | Without a proper reject path, the loop could keep re?running the same draft, burning API budget. | Simulate a draft that passes truncation check; ensure after first `ForgeError` the loop moves to the next candidate instead of re?probing. |
| **Preamble false?negative / positive** | Over?strict or under?strict matching can cause drafts to be rejected or accepted incorrectly. | Add property tests for the preamble detector on sample strings: valid, missing, extra whitespace, different case. |
| **State reset & clear** | Forgetting to clear issue state after rejection could leave a stale ?in?progress? flag. | Inspect `work/draft.rejected.md` and state fields after a rejection run; assert they are cleared. |

** (d) Open questions**

- Exact token?count source: Is `max_tokens` a hard limit on the *generated* draft tokens, or on the *final* response? Need clarification from the spec.
- Cooldown policy details: Starting value (6?h?), doubling rule, and the cap (48?h) are proposed; the actual implementation may differ.
- Preamble detection: The current snippet is truncated; we need the full expected preamble text and the exact regex/function signature.
- How `finish_reason` is currently derived and whether it should be exposed to the caller.
- Whether `DraftRejected` should be a subclass of `ForgeError` or a new exception type; impact on logging and retry loops.
- Where the per?issue cooldown is stored (issue state field, separate table, etc.) and how `pick_next()` / `candidate_issues()` read it.

** (e) Known unknowns**

- Implementation of `model_http` changes (exact return line numbers, parameter names).  
- Exact behavior of the generic handler at line :3420 after a `ForgeError`.  
- The full preamble text and matching rules.  
- Token?count calculation method.  
- State fields used for cooldown and issue release.  

[End of note]

-- swarm/galaxy1
