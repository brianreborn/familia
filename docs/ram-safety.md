# RAM safety (standing rule)

After miryam OOM'd and hard-hung (2026-10-09 PT) while coder (~3 GiB),
embed, and a long compaction self-test ran together, we do **not** aim for
high RAM utilization.

## Policy

1. **Reserve is a floor for the OS and companions**, not leftover scraps.
   On miryam (`ram_mib: 7270`), `reserve_ram_mib` is **3072** so OS,
   hermes-agent, browser, and SSH keep real headroom.
2. **Never pack a host under 8 GiB to less than ~2 GiB free** after the
   graph's estimated node use (weights + KV + 256 MiB overhead +
   `cache_ram_mib`, plus draft weights for active speculative edges in
   schema v2).
3. **One heavy server at a time on miryam.** Do not run embed load tests or
   compaction self-tests alongside the 64k coder server.
4. **Validate against the target host's measured `ram_mib`**, not whatever
   machine happens to run `validate_graph.py`.

## What the validator enforces

| Check | When it fails |
|---|---|
| `estimated_used + reserve_ram_mib > ram_mib` | Graph does not fit the declared reserve. |
| `ram_mib < 8192` and `ram_mib - estimated_used < 2048` | Small-host floor: would leave under 2 GiB free. |

`host.ram_mib` (v1) / `hosts.<name>.ram_mib` (v2) is the measured MemTotal.
If v1 omits `ram_mib`, the validator falls back to this machine's
`/proc/meminfo` MemTotal (only safe when you are on that host).

## Baseline numbers (miryam)

| Placement | Est. use | Free after est. | With reserve 3072 |
|---|---|---|---|
| coder 64k alone | ~2928 MiB | ~4342 MiB | passes |
| coder + embed | ~3479 MiB | ~3791 MiB | passes (tight) |

Adding another active node on miryam without shrinking ctx/cache will usually
fail loud — that is intentional.
