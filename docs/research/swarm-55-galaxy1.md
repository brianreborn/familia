# Survey (Sep?Oct 2026): Models ? speech, audio & voice

Issue: https://github.com/brianreborn/familia/issues/55
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:06 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

And list the top 3 questions you'd ask if this was a real issue.
And end with a clear "TL;DR" (short summary).

TL;DR: The issue is about finding models for speech, audio, and voice. We need to
identify which ones fit the family project's needs, test them on sample data,
and figure out what's missing.

What I need to confirm:

- Which models are actually *trained* for speech, audio, or voice?
- Can we run them on the family's hardware (NVIDIA, Oruk, etc.)?
- What's the runtime/compute cost for each?
- What's the biggest gap between current models and what we need?
- What questions would help us move forward?

Let's get to work.

-- swarm/galaxy1
