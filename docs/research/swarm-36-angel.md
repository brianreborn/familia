# isolated_remote: chat.hf.co returns 402 (no credits); context/compaction/rate limits unmeasured

Issue: https://github.com/brianreborn/familia/issues/36
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:29 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #36: isolated_remote: chat.hf.co returns 402 (no credits); context/compaction/rate limits unmeasured

## Issue Description

The issue involves accessing `chat.hf.co` via `hfchat.py` and encountering a `402 Payment Required` error, indicating that the account has no remaining credits. The goal is to determine the free tier capabilities of `chat.hf.co`, specifically focusing on context tokens, compaction, and rate limits. Additionally, the issue highlights that a non-PTY `ssh -tt` with piped stdin does not submit the prompt.

## Proposed Approach

1. **Test with `/model` for a Free-Tier Model:**
   - Attempt to access `chat.hf.co` using the `/model` endpoint to see if there is a free-tier model available.
   - Measure the response time and any other relevant metrics.

2. **Add HF Credits:**
   - Once a free-tier model is identified or credits are added, measure the session duration, context tokens, compaction, and rate limits.
   - Ensure that the session can handle multiple prompts without hitting rate limits.

3. **Measure Context Tokens and Compaction:**
   - Fill the session step by step to understand the auto-compaction behavior and the maximum single message size.
   - Use the adapter's exit code handling to ensure that the session is rotated before hitting rate limits.

4. **Test Non-PTY `ssh -tt` with Piped Stdin:**
   - Verify that the TUI needs real keystrokes and that a non-PTY `ssh -tt` with piped stdin does not submit the prompt.

## Risks and Test

-- swarm/angel
