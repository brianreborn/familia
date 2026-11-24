# Known issues

- **Historical trap: Nanbeige deployment records (retired 2026-11-23)**
  - The model name was kept in active graph, generated-host, catalog, test, and
    operator records after repeated direction that Angel could not support it.
    That made the keyword act as a poison path: regeneration resurrected a
    deployment that should have been impossible, and the launch path reached a
    license gate instead of a useful host configuration.
  - The model and all active records are purged. This entry is retained only as
    an incident warning. Do not reintroduce the model name, model key, node key,
    or deployment recipe into active configuration.

- **v0.4.0: Windows, FreeBSD and macOS are unverified**
  - **Windows / PowerShell:** untested for v0.4.0. The Windows test hosts (qodesh, shalom) were offline, so the llama `b12359` Windows archives (including CUDA 13.5) and the `.ps1` scripts have not been run. `start.bat` has two F-6 gaps versus the Linux/Termux start path (#631): it ignores its own argv (`--host`, `--port`, `--api-key`), so `start.bat --host 0.0.0.0` exits 0 instead of being refused with exit 2; and `FAMILIA_BIND=0.0.0.0` with `FAMILIA_EXTRA` set to `--tools all` (in cmd.exe: `set "FAMILIA_EXTRA=--tools all"`; single quotes would stay in the value) starts a LAN-bound server with tools on instead of being refused.
  - **FreeBSD / macOS:** the llama.cpp v1.0.0 pin proposed in open PR #614 (code-bootstraps `223bd358`, build `b12359`; main's `pins.txt` is still `6ab58d7` until #614 lands) has only been built on Linux (CPU and Vulkan). Treat FreeBSD and macOS as untested until a build there is recorded; the FreeBSD build and smoke test is must-land #632.

- **hermes fails with HTTP 400 or "below the 64K minimum"**
  - **Cause:** running stock `hermes` with `~/.hermes`. That config has compression off and points at models with small contexts (for example an 8,192-token `general` server), so a long turn overflows the slot and nothing compacts it (seen again 2026-10-18; first in [#19](https://github.com/brianreborn/familia/issues/19)).
  - **Fix:** run `scripts/hermes.sh`. It renders its own config with `context_length` equal to the node's per-slot context (65,536 on `coder`) and compression on. See [QUICKSTART.md](../QUICKSTART.md#always-run-hermes-through-the-harness).
  - **Warm gate:** `warm_prompt` skips when MemAvailable is below `FAMILIA_WARM_MIN_AVAIL_MIB`
    (default 2048) and caps prefill at `FAMILIA_WARM_TIMEOUT` (default 600s) so angel 64K
    mmap+spill cannot hang sole-worker hosts in a multi-hour cache build.

- **Vulkan build stalls under the memory cap with `-ngl 0`**
  - **Cause:** Vulkan llama.cpp builds allocate about 1.8 GB of shared-memory host buffers even with no GPU layers.
  - **Fix:** `scripts/serve.sh` and the hermes harness export an empty `GGML_VK_VISIBLE_DEVICES` for `-ngl 0` nodes. If you start `llama-server` by hand, do the same. Windows `serve.ps1` can't set an empty variable; use a CPU build there. Live re-check: [#40](https://github.com/brianreborn/familia/issues/40).

- **miryam RAM / OOM (standing rule)**
  - **Symptom:** hard hang when estimated llama-server use plus concurrent tests approached full MemTotal (~7.1 GiB).
  - **Rule:** keep ~2+ GiB free on hosts under 8 GiB; miryam `reserve_ram_mib` is 3072. The validator fails on a clear overcommit and warns when the reserve or the 2048 MiB small-host floor would be broken. earlyoom and zram are deployed; the disk swap is still only 16 MiB ([#43](https://github.com/brianreborn/familia/issues/43)). See [ram-safety.md](ram-safety.md).

- **Embedding node deferred**
  - The `embed` node (EmbeddingGemma-2) is still declared in `graph.yaml` but deferred until further notice ([#38](https://github.com/brianreborn/familia/issues/38)). Don't run it next to the coder on miryam.

- **Transient errors from remote models**
  - **Symptom:** a remote model occasionally returns an empty response, HTTP 503 or a timeout.
  - **Workaround:** retry the request. `scripts/retry_wrapper.py` exists but no caller uses it yet ([agy-retry-config.md](agy-retry-config.md)).

- **One known test failure**
  - `tests/test_ram_safety.py::test_overcommit_is_hard_error` fails on hosts that have the coder and embed model files, because the test graph trips an earlier reserve error first.
- **Server Tools stay on across restart (#630)**
  - llama.cpp enables Server Tools only when the process is started with `--tools`.
    A crash restart, a hand-start, or a stale `generated/graph-*.yaml` used to drop
    the flag, and `GET /tools` returned 403 `feature_disabled`.
  - `familia-start` now saves the `--tools` value for that port (mode 0600,
    `$XDG_CONFIG_HOME/familia/server-tools/<port>`, or `~/.config/familia/server-tools/<port>`)
    and reapplies it when a later start omits the flag. `--tools none` clears the save.
  - `start.sh` and `serve.sh` copy `server_tools` from `graph.yaml` onto a generated
    graph that dropped the key. An explicit key on the graph being launched, including
    an opt-out (`[]` / `none` / `false`), wins.
  - `--tools` remains loopback-only. Every listener still requires an API key.
    `hermes_harness.ensure_server` still refuses to adopt a live port whose graph asks
    for tools while `/tools` is feature_disabled. Do not grant `--tools` on a node
    where the live `tool_policy` would refuse that tool.
