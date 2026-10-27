# Valid perf results — 2026-10-27

Fresh miryam smoke after L-memcg invalidation of Oct 19 capped runs.
No `MemoryMax` / memcg. Host lock via `scripts/with-host-lock --big`.

## Hosts
| host | status | notes |
|---|---|---|
| miryam | online | SmolLM2-135M-Instruct Q4_0 CPU short smoke |
| phone8 | committed Oct 10 anchor reused | Termux SSH timed out this session; Cursor A57 connected but no shell |
| centos10-bigram, qodesh, shalom | offline | no numbers invented |

## Fresh valid (miryam)
SmolLM2-135M-Instruct Q4_0, llama-bench b11935, `-lm none -ngl 0 -p 256 -n 64 -r 1`:

| threads | pp256 tok/s | tg64 tok/s |
|---|---|---|
| 1 | 166.35 | 62.59 |
| 2 | 222.15 | **85.71** (best tg) |
| 3 | 291.14 | 54.91 |

Exact argv and sha256 in `miryam-smollm2-smoke.meta.txt` / `.jsonl`.
Labels are model name + quant, never a hash.

## Invalid (shown only for contrast)
Oct 19 miryam/CentOS numbers gathered under `MemoryMax=3500M` are **INVALID** (LESSONS-LEARNED `L-memcg`, #95). Listed in `fleet-perf-summary.json` with `valid=false`.
