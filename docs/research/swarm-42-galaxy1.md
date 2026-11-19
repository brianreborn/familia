# Live-run hermes --selftest-compaction on miryam (#19 follow-up)

Issue: https://github.com/brianreborn/familia/issues/42
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:58 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

And, if possible, point to relevant git commits or files.

---

You are a careful engineer on the familia project writing a short first-pass work note in plain ASCII markdown for this GitHub issue.

### 1. What is the problem?
- **Goal:** Run `hermes.sh --selftest-compaction` against miryam.
- **Problem:** It fails to run; host drops, memcap stalls, or credit is cut.
- **Why:** Not enough resources/context for the test to finish.

### 2. Proposed approach
- **Check environment:** Ensure `--selftest-compaction` is properly configured (e.g., correct flags, memcap, CPU-only).
- **Increase resources:** Use `--escalate` or run with a more powerful machine (if possible).
- **Inspect logs:** Capture the full selftest summary and error traces.
- **Check dependencies:** Verify miryam and dependencies are up to date.

### 3. Risks & test ideas
- **Risks:** Test hangs, incomplete tests, missing resources, incorrect flags.
- **Test ideas:** 
  - Run with `--verbose` to see detailed output.
  - Add `--timeout` or `--max-time` to force a timeout.
  - Check if the test is being blocked by a slow dependency.

### 4. Open questions
- What environment variables or flags are missing?
- Is the test harness properly configured?
- Should we try a different test harness or a different version?

---

*Note: This is a first-pass note. Replace placeholders with actual details if you have them.*

-- swarm/galaxy1
