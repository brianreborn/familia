# RT idea: evaluate targeted weight edits that fix small-model reasoning loops (Qwen3.5-0.8B)

Issue: https://github.com/brianreborn/familia/issues/299
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:53 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

---

# Code-bootstraps-llama.cpp small-model defaults (Qwen3.5-0.8B)

Promoted by **RT Scout** (R&D scout agent for Brian's projects) after three independent reviewer approvals. Research only: not part of any pre-release sprint, and nothing here authorizes installs on fleet hosts, pushes, or merges.

Also relevant to code-bootstraps-llama.cpp small-model defaults. Gate from Senior Developer review: stop if no edited weights or diff are published.

Idea card (box copy): `/workspace/research/rt-scout/cards/weight-space-programming-small-model-edit.md`. Full card text, including the source posts and every review with its conditions, follows.

---

# Targeted weight edits to fix a small model's reasoning loops ("Weight-Space Programming")

- **Source (Brian's repost, @BrianReborn_alt):** https://x.com/i/status/[number]
- **Original post:** https://x.com/i/status/[number] (@rikiyatakehi, [number])
- **Quote from post:** "We asked GPT-6 Astra to edit Qwen3.5-0.8B weights to improve math. It directly changed only 0.016% of weights, fixing 0.8B's reasoning loops & improving math up to 6x and even instruction following 3x, without gradients or training."

## Core idea
Instead of fine-tuning, have a strong model propose a tiny, targeted set of direct weight changes to a small model, then keep the edit only if benchmarks improve. The poster

-- swarm/box
