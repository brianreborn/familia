# Terminal-RSI (#88 / #68)

Status: design notes / scaffolding (Continuity `swarm/continuity/terminal-rsi`).
Sources: #88 (Tencent Terminal-RSI), #68 (related survey / prior note).

Tweet: https://x.com/BrianReborn_alt/status/2111884222025843098

## Thesis

Self-rewrite of successful trajectories + policy refinement as a familia
agent-tuning pipeline. Works with both hermes and Harness².

## Familia hooks

- Trajectory capture: dogfood / hermes-agent transcripts (tools limited to
  worktree when under dogfood; see #110 — Hermes Wiring owns live loops).
- Policy/prompt refine output → `harness/` overlays or hermes `HERMES_HOME`
  skill/prompt patches (ref Harness² propose path, #87).
- Benchmark suite: fixed terminal tasks; CentOS + phone where model fits;
  exact per-weight-file params in `docs/perf/`.

## First implementation slice (later)

1. Schema for trajectory JSONL (task id, tools, success, prompt hash).
2. Offline refine script: successful traj → candidate prompt delta.
3. Gate with existing accept tests before promoting into harness configs.

## Non-goals this tip

- Full arxiv/PDF port
- Live RSI loop on 8600 / GGUF policy changes
- Colliding with Researcher #150 graph work
