# API key design (familia)

Canonical design: https://github.com/brianreborn/code-bootstraps-llama.cpp/blob/feat/stable-key-source-build/docs/api-key-design.md

Summary: one stable key per instance/port, stored 0600 under XDG_CONFIG_HOME (APPDATA on Windows), written atomically, never regenerated on :9931 startup. Every caller sends the key. A 401 means "server up, wrong/missing key" and is never treated as "no server".

## Forwarding to nested callers (familia side)

`scripts/familia_auth.py` is the single helper.

- `ensure_instance_key()` / `familia_auth.py ensure` creates the key once per instance (atomic, 0600) and never rotates it.
- Every HTTP caller uses `request()` / `open_url()` / `auth_headers()`. Harness² `chat()` (called recursively by the self-improve engine) fails closed with `MissingKey`.
- Every process that spawns another familia caller uses `child_env()`. The child gets `API_KEY_FILE` (path) plus `FAMILIA_PORT`, never the key value, so it resolves the same instance key. Wired in:
  - `hermes_harness.hermes_child_env`, and through it `scripts/dogfood/hermes_loop.py`'s render and oneshot steps
  - `scripts/dogfood/harness2_loop.py` → `harness2.py propose`
  - `with-fleet.sh` → `serve.sh` (guardian `--operator-start`) and `hermes.sh`. These fail closed when no key can be ensured.
- `graph.yaml` `gateways.roomz` (port 9931) documents the requirement and holds no secret. `generated/graph-*.yaml` is regenerated from `graph.yaml`.
