# Known issues

- **v0.4.0: Windows, FreeBSD and macOS are unverified**
  - **Windows / PowerShell:** untested for v0.4.0. The Windows test hosts (qodesh, shalom) were offline, so the llama `b12359` Windows archives (including CUDA 13.5) and the `.ps1` scripts have not been run. `start.bat` has two F-6 gaps versus the Linux/Termux start path (#631): it ignores its own argv, so `start.bat --host 0.0.0.0` exits 0 instead of being refused with exit 2; and `FAMILIA_BIND=0.0.0.0` with `FAMILIA_EXTRA='--tools all'` starts a LAN-bound server with tools on instead of being refused.
  - **FreeBSD / macOS:** the llama.cpp v1.0.0 pin (code-bootstraps `223bd358`, build `b12359`) has only been built on Linux (CPU and Vulkan). Treat FreeBSD and macOS as untested until a build there is recorded.

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
- **angel Nanbeige / llama-ui showed no Server Tools (M0)**
  - **Cause:** `llama-server` started without `--tools`. `/tools` returns HTTP 403
    `feature_disabled`; llama-ui then shows an empty tools panel. Template still has
    `chat_template_caps.supports_tools=true`. `/v1/models` `capabilities:["completion"]`
    and default `chat_format: Content-only` are normal without an active tools request —
    not the regression by themselves.
  - **Fix:** set `nodes.<name>.server_tools: all` (or a tool-name list) on loopback-bound
    nodes; `validate_graph`/`serve.sh` emit `--tools …`. `nanbeige-coder` has this. Restart
    the node (DETACH_MODE=screen-attached) after changing the graph.
  - **Recurrence (2026-10-27):** `--tools` is launch-only. After a crash/restart, an argv
    without `--tools` (hand-start, or stale `generated/graph-*.yaml`) empties the panel again
    even though `graph.yaml` still has `server_tools: all`. Verify live argv + `GET /tools`,
    not only the graph field. See LESSONS-LEARNED `L-server-tools`.
  - **Harness:** `hermes_harness.ensure_server` will not daemon-spawn a missing node and will
    refuse to adopt a live port when `server_tools` is set but `/tools` is feature_disabled.
  - **No v0.4.0 waiver:** the launch-only `--tools` limit is v0.4.0 must-land
    [#630](https://github.com/brianreborn/familia/issues/630) and blocks the tag. Until it
    lands, after a crash, a hand-start, or a stale `generated/graph-*.yaml`, check
    live argv and `GET /tools` before treating Server Tools as available. `server_tools` in
    `graph.yaml` is necessary but not sufficient. See LESSONS-LEARNED `L-server-tools`.
    Do not grant `--tools` on a node where the live `tool_policy` would refuse that tool.


