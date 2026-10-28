# Miryam coder perf — Race seatbelts (#83 / #82)

Partner: Platform `swarm/platform/vulkan-cuda-miryam` → `docs/platform/gpu-path-layout.md`
(on that branch; box mirror: `/workspace/reviews/gpu-path-layout-miryam.md` until it lands on main).

Race owns spawn races on `swarm/race/miryam-perf`. Platform owns discover order, RPATH /
`LD_LIBRARY_PATH` / ICD, Termux `PREFIX`, and `refuse_soname_skew`. **Win** empty-env /
`serve.ps1` is out of this cut. Live llama restarts only with `DETACH_MODE=screen-attached`.

## #83 — Vulkan build + `-ngl 0` tanks TTFT (~4.7×)

Measured 2026-10-19 (`docs/perf/2026-10-19-tuning-2.md`): Vulkan prebuilt with `-ngl 0`
still op-offloads to HD 620; TTFT 7.29 s vs 1.56 s on a native CPU build.

**Policy (per child process, never login-shell):**

1. Prefer a **CPU pack** `runtimes.*.bin` when `offload.ngl == 0` or `backend: cpu`
   (`scripts/miryam_perf_seatbelts.prefer_cpu_runtime_bin`, wired from
   `validate_graph.server_args`).
2. If only a Vulkan pack is available: keep empty `GGML_VK_VISIBLE_DEVICES` via
   `server_env` / `serve.sh` (L-vkshm) **and** pass `--no-op-offload`.
3. Do **not** unset `VK_ICD_FILENAMES` or wipe Mesa ICD in the user profile — same host
   may run decision `ngl: 99` beside coder `ngl: 0`.

`serve.sh` also adds `--no-op-offload` on the Vulkan→CPU failure retry and when `-ngl 0`
args still point at a `*vulkan*` binary.

## #82 — `ngram-simple` can make generation ~6.8× slower

On mixed / non-repetitive turns, rejected drafts on Qwen3.5 recurrent layers cost rollbacks.
The earlier 2.2× gain was full-file echo edits only.

**Policy:**

- `speculative.coder-ngram` is **`status: planned`** (opt-in). No silent default on mixed turns.
- When enabling, prefer **`spec_type: ngram-mod`** (graph default) over `ngram-simple`.
- `server_args` only emits `--spec-type …` when status ≠ `planned` (unchanged rule).

## Hooks

| Hook | Where |
|------|--------|
| `server_env` empty VK devices | `scripts/validate_graph.py` |
| CPU prefer + `--no-op-offload` | `scripts/miryam_perf_seatbelts.py` → `server_args` |
| `check_soname_skew` | Soft→hard Race refuse: Platform `refuse_soname_skew` `{ok:false}` hard-refuses; ImportError soft-skips. `start_graph` / `serve.sh` / `harness2` |
| `capture_spawn_fingerprint` + `assert_fingerprint_stable` | Race TOCTOU: capture after first refuse; re-stat `fingerprint(bin)` late before Popen/exec; compare `bin` + `libs[]` `ino`/`mtime_ns`/`size`/`dev` directly (no `fingerprints_equal`); refuse `soname_fingerprint_drift`. Platform SHA compose target: `e49bce1` |
| Thread budget | Keep `with-host-lock` / fleet admission; soft note if CPU node `-t` > 4 beside same-host active Vulkan peer (resident 4 / sprint 6) |

## Deferred

- Live miryam re-measure after merge (DETACH_MODE=screen-attached).
- angel / fam-gpu CUDA path (Platform + measured NVIDIA).
- Win CPU empty-env / PS 5.1.
- Live compose once Platform `refuse_soname_skew` (`e49bce1`) lands on main; Race already soft-imports.
