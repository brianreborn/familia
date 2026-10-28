# Jev harness slimming (#89)

Status: design notes / scaffolding (Continuity `swarm/continuity/jev-89`).
Source tweet: https://x.com/BrianReborn_alt/status/2112052407991697597

## Thesis

"The harness, not the model, is the bottleneck." Mine the Jev harness-building
guide for prompt and harness slimming; apply findings to familia (#85 lean path).

## Existing familia surface

- `docs/harness-slimming.md` — current lean rules
- `scripts/hermes_harness.py` — `LEAN_AUX_DROP`, base/guardrails
- `scripts/measure_prompt.py` — token/char counts for hermes lean + Harness² base
- `tests/test_harness_slimming.py` — base prompt size + lean drop invariants
- `harness/base/systemprompt.md`, `harness/base/guardrails.md`

## Planned changes (do not block on PDF/arxiv full port)

1. Extract concrete slimming recipes from the Jev PDF when available under
   `docs/research/` (prompt budget, tool surface, memory/skills gating).
2. Apply to hermes lean render + Harness² base prompts; keep `measure_prompt.py`
   green with tighter budgets.
3. Measure fixed-prompt token count + first-turn latency on CentOS and phone
   with exact per-weight-file params; record under `docs/perf/`.
4. Cover both hermes and Harness² in tests (ref #86, #85, #87).

## Non-goals this branch tip

- Full PDF ingestion / OCR pipeline
- Changing gum home front door
- Dogfood dispatch (#110 — Hermes Wiring)
