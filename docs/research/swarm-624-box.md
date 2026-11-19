# swarm-pull #580 gaps beyond #616: truncation check, reject/release/backoff path, preamble and fence coverage

Issue: https://github.com/brianreborn/familia/issues/624
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:16 PST
Approved-content-sha256: c74e7eff1c6d7e6e08ae15ddf81227a5a1a1f68f56620d043d7fbfab1d531b6a

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18114); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

[Issue #624 summary]

**What the issue asks**

The #580 acceptance criteria has gaps that were not yet closed in #616. Specifically for the *swarm-pull* feature (checked on main at commit 26d9720 in `scripts/swarm/swarm-pull`), three things are missing or broken:

1. **Truncation check** ? `model_http` (lines ~2456?2484) currently only returns `choices[0].message.content` and drops `finish_reason`. The CLI path has no ?stop signal?. A draft that is cut off at `max_tokens` passes `validate_draft` even if it is over 200 characters and has balanced fences.  
   *Fix*: make `model_http` return `(text, finish_reason)` and reject the ?length? case. For the CLI path, reject when the generated token count reaches or exceeds `max_tokens`.

2. **Reject / release / backoff path** ? After #616 makes validation raise a `ForgeError`, the run loop?s generic handler (:3420) just logs, sleeps (retry) and keeps the claim. The next iteration re?runs the probe and the model on the same issue; nothing changes until `HoldExhausted`. The runner that *rejects* the draft keeps the issue, burns model time and API budget each loop, and no other runner can pick it up.  
   *Fix*: introduce a dedicated exception class `class DraftRejected(ForgeError)` with a reason class (e.g. `nonce|fence|preamble|unbalanced|truncated|short`). Write `work/draft.rejected.md`. In the loop, handle it like `NotApproved`: call `release_issue(repo, n, "draft rejected: <class>", claim=claim)`, clear the state, and record a per?issue cooldown (e.g. 6?h, doubling, capped at 48?h) that `pick_next()` / `candidate_issues()` honor.

3. **Preamble detection** ? The current detection only matches a partial phrase (?You are ??) and is incomplete; the issue is cut off but indicates that preamble matching needs to be fixed.

**Goal**

Make the validation of drafts in the swarm?pull flow robust: reject drafts that are too long, properly signal the reason, give the CLI a stop condition, and ensure a single runner owns a rejected draft by adding a cooldown that other runners can wait for before re?probing.

---

### (a) What the issue asks ? in my own words

We need to close three gaps in the *swarm?pull* implementation (as of main @ 26d9720, `scripts/swarm/swarm-pull`):

1. **Truncation / length handling** ? `model_http` should return both the text and the `finish_reason`; it should also reject drafts that exceed `max_tokens`. The CLI path must have a ?stop when tokens >= max_tokens? signal. Currently a draft that is over 200 characters and has balanced fences passes `validate_draft` even though it was cut off.

2. **Reject path & back?off** ? When validation raises a `ForgeError`, the generic run?loop handler (:3420) just logs, sleeps and keeps the claim, causing a livelock. We must add a dedicated `DraftRejected(ForgeError)` with a reason class (nonce, fence, preamble, unbalanced, truncated, short). The loop should treat it like `NotApproved`: release the issue, clear state, and enforce a per?issue cooldown (e.g. 6?h, doubling, max 48?h) that `pick_next()` / `candidate_issues()` respect.

3. **Preamble detection** ? The current preamble matcher only handles a partial phrase and is incomplete; we need to finish the logic (but details are cut off).

---

### (b) Proposed approach & likely files / components

**High?level plan**

| Area | Change | Files / Components |
|------|--------|--------------------|
| `model_http`

-- swarm/box
