# Model registry and hardware registry

Measured results decide where models run. Instead of re-sweeping a machine, look up
what was already measured on it (or on identical hardware) and get a placement from that.

## Layout
| path | what | shareable |
|---|---|---|
| `registry/records.jsonl` | append-only results, one JSON object per line | yes (host names are ours) |
| `registry/hardware/<id>.yaml` | hardware profiles keyed by hardware identity | **yes, no private data** |
| `registry/hosts.yaml` | our host name -> profile id | private mapping |
| `registry/seed_2026-10-10.py` | one-off transcription of results already published in this repo | - |

## Record fields
`host`, `hardware_profile`, `device` {kind, name, backend, driver}, `runtime` {name, commit or pkg},
`model` {repo, file, sha256, arch, quant, size_mib, db_id, revision, db_match | db_note} (db_id: the `registry/models/` entry, see docs/model-database.md; null with a db_note when the match is ambiguous), `settings` {ngl, threads, batch, ubatch, fa,
kv_type, ctx, rows_per_thread, ...}, `metrics` {pp_tps, tg_tps as {min, max, measured}, latency_ms,
ram_peak_mib, vram_peak_mib, free_ram_min_mib}, `concurrency` {co_runner, co_runner_tps,
co_runner_alone_tps} or null, `correctness` (e.g. "32/32 vs CPU ref"), `power` {measured, watts,
method, source}, `timestamp` (with offset), `timestamp_approx` when only the order is known,
`source` (commit, file@branch, or issue URL).

Rules: every metric says `measured: true|false`. Estimates carry `method` and `source`. Nothing is
filled in from memory or guessed; leave it null.

## Commands
```
python3 scripts/registry.py summarize
python3 scripts/registry.py query --host miryam --backend vulkan
python3 scripts/registry.py suggest --host miryam --role decision   # ranked + graph.yaml snippet (not written)
python3 scripts/registry.py power                                   # watts + tok/J per placement (estimates labelled)
python3 scripts/registry.py match --measure-json host.json          # or --graph graph.yaml --host NAME
python3 scripts/registry.py lint                                    # profiles carry no IPs/users/keys/hostnames
```
`suggest` ranks by measured tg t/s x measured contention factor (from a concurrent record of the
same device+model), halves the score if a record broke the 2 GiB free-RAM floor
(docs/ram-safety.md), and reports watts and tokens per joule. If the host has no records, it borrows
from another host with the same hardware profile and flags that as interpolated.
`validate_graph.py` now warns (never fails) when a node has no registry evidence.

## Power budget
Per-profile figures come from vendor spec pages (cited in each profile): 8600 GT 47 W max board power,
i5-7200U 15 W package TDP (HD 620 shares it), Galaxy A57 5000 mAh battery and 10-45 W charging.
Watts per placement are upper-bound **estimates** until measured; tok/J = t/s / W.
Phone sustained-load watts (5 W) are an assumption, labelled as such.
Measurement hook: `scripts/power_probe.sh [seconds]` (RAPL on Linux if readable without sudo;
termux-battery-status or sysfs current_now/voltage_now on Android). It starts no load, so run it beside a
benchmark that is already running and put its JSON into the record's `power`. The 8600 GT has no
sensor (nvidia-smi does not support G84), so it stays unmeasured unless a wall meter is used.

## For workers pushing tuning results now
1. After each measured run write one JSON record (fields above) and run
   `python3 scripts/registry.py add rec.json`. Never edit or delete existing lines; if a result was
   wrong, append a correcting record with `supersedes: <timestamp+host>` and the reason.
2. Include runtime version (L9), correctness result, and the concurrency context, or null if it ran alone.
3. Commit `registry/records.jsonl` with the result it came from and pull with rebase before pushing (append-only lines merge cleanly).

## Hardware registry: matching and contributing
Profiles are keyed by device model/SKU, SoC/board, GPU + driver, OS build, RAM and runtime version,
not by our host names. Each holds the known-good setup, best measured settings, gotchas, power notes,
and `records.hardware_profile` to find the matching result records.
`registry.py match` takes `install/host_measure.py` output (cpu, os, ram_mib; add sku, board,
gpu_driver, runtime if known), picks the profile, prints the setup and pre-filled defaults, and warns
on SKU, RAM, driver or runtime mismatch.

**Contributing a profile (outsiders welcome):** open a PR adding
`registry/hardware/<vendor>-<model>-<soc>-<os>.yaml` in the format above plus your records in
`registry/records.jsonl` (use a generic `host` such as `contrib-1`). `registry.py lint` must pass:
no IPs, usernames, keys or host names. Mark every number measured or estimated, with its source.
