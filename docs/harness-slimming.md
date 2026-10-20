# Harness slimming (#89)

> Status: applied. Coordinates with [#85](https://github.com/brianreborn/familia/issues/85)
> (lean profile + prompt-prefix cache). Does not reopen #85's cache work.

## Thesis (Jev / TypeSafe)

Public notes around TypeSafe's Jev and the "harness, not the model, is the
bottleneck" claim (Diogo Amogo / Jev engineering write-ups; see #86 → #89):

1. **Freeze the strategy in the harness.** Do not regenerate long reasoning
   every turn. Keep the system prompt short; put rare guidance in skills.
2. **Narrow the visible tool surface.** Extra tool schemas dominate fixed
   prompt tokens on small local models.
3. **Keep code in control.** Prefer structured config and skills over a
   growing system prompt.
4. **Self-improve must not widen tools.** familia's Harness² gate already
   rejects tool/plugin/permission widening (`scripts/self_improve.py`).

The exact PDF linked from the source post was not mirrored here (X article);
principles above are taken from TypeSafe docs (`how-to-build-with-system-one`,
`coding-agents`) and the JevHarness project README, which match the issue text.

## What landed

| Layer | Change |
|---|---|
| `harness/base/*.md` | Shorter system prompt + guardrails (~100 tok combined target) |
| `hermes_harness.py` | Lean profile also drops unused aux tasks (`LEAN_AUX_DROP`) |
| `scripts/measure_prompt.py` | File-token estimate; optional `/tokenize` endpoint |
| Harness² | Same `harness/base` files; gate unchanged (no tool widening) |

#85 already landed lean toolsets (5) + slot save/restore. This issue only
adds aux-task dropping and the base-harness rewrite so both hermes and
Harness² share the slim surface.

## Measure

```sh
scripts/measure_prompt.py
scripts/measure_prompt.py --endpoint http://127.0.0.1:9941/v1   # if a server is up
```

Record exact per-weight-file params in `docs/perf/` when you bench.
