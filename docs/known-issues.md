# Known issues

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
    nodes; `validate_graph`/`serve.sh` emit `--tools …`. `angel-coder` has this. Restart
    the node (DETACH_MODE=screen-attached) after changing the graph.
  - **Recurrence (2026-10-27):** `--tools` is launch-only. After a crash/restart, an argv
    without `--tools` (hand-start, or stale `generated/graph-*.yaml`) empties the panel again
    even though `graph.yaml` still has `server_tools: all`. Verify live argv + `GET /tools`,
    not only the graph field. See LESSONS-LEARNED `L-server-tools`.
  - **Harness:** `hermes_harness.ensure_server` will not daemon-spawn a missing node and will
    refuse to adopt a live port when `server_tools` is set but `/tools` is feature_disabled.

