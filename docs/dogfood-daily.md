# dogfood-daily

Accept rate per harness/model for the familia dogfood loop
(`scripts/dogfood/dispatch.py`, `#110`).

Each dispatcher run also writes `$OUT/dogfood-daily.md` (default
`~/.cache/familia/dogfood/`). Pass `--record-docs` to refresh this file.

## Harnesses (real loops, not single chat calls)

| harness | real CLI | smoke switch |
|---|---|---|
| `hermes` | `scripts/hermes.sh --mode single` + `hermes-agent -z` in the task worktree | `--render-only` (+ argv check) |
| `hermes-graph` | `scripts/hermes.sh --mode graph` + `hermes-agent -z` in the task worktree | `--render-only` (+ argv check) |
| `harness2` | `scripts/harness2.py propose --target hermes-lab` | `--dry-run` |

Tools for hermes oneshots are limited to `file,terminal,todo` with `cwd` = the
task worktree (`FAMILIA_SYNC=0` on worktree create; see `#111`). Host lock /
thread admission still wrap live runs (`scripts/with-host-lock`,
`bench_guard.threads_in_use`).

## Live-land gap (miryam, 2026-10-27 America/Los_Angeles)

miryam had ~1–3.5 GiB MemAvailable and a broken/missing
`Qwen3.5-2B-Q4_K_M.gguf` symlink when this wiring landed. The coder node needs
64K ctx and the host reserve is 3072 MiB, so a live oneshot / Harness² propose
was not run here. **Next step:** restore the coder GGUF, start
`DETACH_MODE=screen-attached sh scripts/serve.sh coder` under the host lock,
re-run `dispatch.py` without `--smoke`, and land one real iteration per
harness. Leave `#110` open until those live lands verify on `origin/main`.

## Rates

| harness/model | ok | n | rate | smoke |
|---|---:|---:|---:|---:|
| harness2/hermes-lab | 1 | 1 | 100% | 1 |
| hermes-graph/coder | 1 | 1 | 100% | 1 |
| hermes/coder | 1 | 1 | 100% | 1 |

