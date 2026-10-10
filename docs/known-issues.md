# Known Issues

- **Model:** GPT-OSS-120B-MEDIUM (transient errors)
  - **Symptom:** Occasionally the model fails with an internal error or timeout during inference, often returning an empty response or HTTP 503.
  - **Temporary Workaround:** Pend a retry of the request. A retry wrapper exists (`scripts/retry_wrapper.py`) but is not wired into any caller yet, so retry manually. This covers transient server-load conditions.

- **Host:** miryam RAM / OOM (standing rule)
  - **Symptom:** Hard hang when estimated llama-server use plus concurrent tests approached full MemTotal (~7.1 GiB).
  - **Rule:** Keep ~2+ GiB free on hosts under 8 GiB; miryam `reserve_ram_mib` is 3072. See `docs/ram-safety.md`. The graph validator fails if `estimated + reserve > ram` or if free-after-estimate drops below 2048 MiB on small hosts.

