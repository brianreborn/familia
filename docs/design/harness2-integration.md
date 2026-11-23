# Harness² integration (#87 / #65)

Status: design notes / scaffolding (Continuity `swarm/continuity/harness2`).
Sources: #87 (Google Harness²), #65 (related).

Tweet: https://x.com/BrianReborn_alt/status/2111985618674970917

## Thesis

Integrate Google's open-source Harness² (self-improving prompt/tools/memory/
skills/subagents) as a first-class familia harness and as hermes's
self-improvement loop.

## Existing familia surface

- `scripts/harness2.py` — propose / enable / dry-run entry
- `docs/harness2.md` — current operator notes
- `tests/test_harness2.py`
- Dogfood path calls `harness2.py propose` (#110 — Hermes Wiring owns live
  dogfood land; Continuity keeps harness product track)

## Planned work

1. Confirm upstream Harness² pin / vendor policy (prefer submodule or documented
   install; avoid inventing `/usage`).
2. End-to-end launch under familia (routing, logs) on CentOS + phone vs hermes
   and plain llama.cpp; exact per-weight-file params → `docs/perf/`.
3. Honest stub hooks remain until upstream vendored; link issues from stub
   messages (no silent no-ops).
4. Gum home stays primary; no catalog front-door revival.

## Non-goals this tip

- Full upstream port without a pin
- Merging to main without Brian exact yes
- Touching #150 graph / host-prefixed node names
