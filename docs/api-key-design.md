# API key design (familia)

Canonical design: https://github.com/brianreborn/code-bootstraps-llama.cpp/blob/feat/stable-key-source-build/docs/api-key-design.md

Summary: one stable key per instance/port, stored 0600 under XDG_CONFIG_HOME (APPDATA on Windows), written atomically, never regenerated on :9931 startup. Every caller sends the key. A 401 means "server up, wrong/missing key" and is never treated as "no server".

Project rule (DESIGN.md Security, CFG-CRED-009): any service listening on the network must require an API key. Localhost-only without a key is allowed only for the named local-development-tool exceptions listed in DESIGN.md. familia llama-server launchers (`scripts/serve.sh`, `familia-start`, `scripts/windows/start.bat`) are not exceptions: they require a key on every bind, including loopback. `validate_graph.py --args` always includes `--api-key-file`; `scripts/bind_auth_guard.py` refuses a launch that would bind without one. The file must be owner-readable and not group- or world-readable (mode 0600 or 0400).

## Two on-disk layouts (no migration yet)

Canonical for graph-launched nodes (`scripts/serve.sh`, `scripts/windows/start.bat`, `graph_router`, and the default path in `scripts/familia_auth.py`): `~/.config/familia/instances/<port>/api-keys` (`%APPDATA%\\familia\\instances\\<port>\\api-keys` on Windows). Clients honor `API_KEY_FILE` or `FAMILIA_API_KEY_FILE` as an override.

`familia-start` (Linux, Termux, FreeBSD installers) uses `~/.config/familia/api.key` (one token, no newline) and `FAMILIA_API_KEY_FILE`. There is no migration between the two layouts ([#419](https://github.com/brianreborn/familia/issues/419)). Until that lands, `familia_auth` also looks at the default installer `api.key` path after the per-instance file.


## Callers on the familia side (established mechanisms only)

- The key is created once per instance by code-bootstraps `serve.sh` (`instance_key_ensure`, 0600, atomic, honours `API_KEY_FILE`). llama-server reads it from `LLAMA_API_KEY`. Router children inherit that, and router->child calls forward the caller's `Authorization` / `X-Api-Key` (patch 0001).
- familia HTTP callers use `scripts/familia_auth.py` (`request` / `open_url` / `auth_headers`). This includes the Harness² `chat()` and `endpoint_up` in `harness2_local.py`; `chat()` fails closed with `MissingKey`.
- Nested processes (dogfood hermes/harness2 loops, `hermes.sh`, `serve.sh`) inherit the parent's environment (`API_KEY_FILE`, `FAMILIA_API_KEY_FILE`, `FAMILIA_API_KEY`, `LLAMA_API_KEY`) and otherwise resolve the same per-instance file. No extra forwarding layer.
- `with-fleet.sh` refuses to exec `hermes.sh` when `familia_auth.py has-key` fails.
- `graph.yaml` `gateways.roomz` (port 9931) holds no secret.
