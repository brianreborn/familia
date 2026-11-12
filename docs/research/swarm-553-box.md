# v0.3.0 release 2/4: ship reasonable default model graphs per platform tier

Issue: https://github.com/brianreborn/familia/issues/553
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 05:12 PST

Status: First-pass notes. Section 1 is a read-only probe run on the runner host.
Section 2 outlines the default model graph requirements across platform tiers.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Platform Tier Analysis & Requirements

### Desktop Linux / macOS Tier
- Roles covered: chat, coder, general, reasoning, embed, vision.
- Target models: balanced open-weights (e.g. Qwen2.5-Coder-7B/14B, Llama-3.1-8B, embedding models).

### FreeBSD CPU Tier
- Roles covered: small speculative coder, lightweight chat.
- Constraints: CPU only, low RAM overhead, no massive offloads.
- Target pair: Qwen2.5-Coder-3B with Qwen2.5-Coder-0.5B draft.

### Mobile / Android Termux Tier
- Roles covered: lightweight local assistance, decision.
- Constraints: mobile memory envelope, battery and thermal limits.
- Target class: LFM2.5-1.2B / SmolLM2-135M class models.

### Open Questions & Next Steps
- This PR serves as an initial requirements outline and does NOT close #553.
- Actual graph modifications belong in graph.yaml per tier without mass-activating nodes.

-- swarm/box
