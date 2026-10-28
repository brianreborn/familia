# dogfood-daily

Accept rate per harness/model for the familia dogfood loop
(`scripts/dogfood/dispatch.py`, `#110`).

Adapters: `scripts/dogfood/hermes_loop.py` (single + graph) and
`scripts/dogfood/harness2_loop.py` (Harness² propose). See
`docs/dogfood-hermes-loop.md`.

Each dispatcher run also writes `$OUT/dogfood-daily.md` (default
`~/.cache/familia/dogfood/`). Pass `--record-docs` to refresh this file.

## Harnesses (real loops, not single chat calls)

| harness | real CLI | smoke switch |
|---|---|---|
| `hermes` | `hermes_loop` → `hermes.sh --mode single` + `hermes-agent -z` in worktree | `--render-only` (+ argv/bin check) |
| `hermes-graph` | `hermes_loop` → `hermes.sh --mode graph` + `hermes-agent -z` in worktree | `--render-only` (+ argv/bin check) |
| `harness2` | `harness2_loop` → `harness2.py propose --target hermes-lab` | `--dry-run` |

Tools for hermes oneshots are limited to `file,terminal,todo` with `cwd` = the
task worktree (`FAMILIA_SYNC=0` on worktree create; see `#111`). Host lock /
thread admission still wrap live runs (`scripts/with-host-lock`,
`bench_guard.threads_in_use`). Hermes bin via `hermes_harness.resolve_hermes`.

## Live-land gap (follow-up)

Smoke proves real CLI invocation without weights. Live oneshot / Harness²
propose still needs a host with coder GGUF + MemAvailable above
`hosts.*.reserve_ram_mib`, then:

```sh
DETACH_MODE=screen-attached sh scripts/serve.sh coder   # under with-host-lock
python3 scripts/dogfood/dispatch.py QUEUE.yaml --harness hermes,hermes-graph,harness2
```

Leave `#110` open until one live accept per harness lands on `origin/main`.

## Rates

| harness/model | ok | n | rate | smoke |
|---|---:|---:|---:|---:|
| harness2/hermes-lab | 1 | 1 | 100% | 1 |
| hermes-graph/coder | 1 | 1 | 100% | 1 |
| hermes/coder | 1 | 1 | 100% | 1 |
