# Credential convention (all config files)

| ID | Rule | Status | Pointer |
|---|---|---|---|
| CFG-CRED-001 | No secret value is ever committed in any tracked config (graph.yaml, registry, docs, tests). Only env var **names** or secret **file paths** | IMPLEMENTED for agents.mcp (schema rejects literal env/headers) | graph_types.py:318-333 |
| CFG-CRED-002 | MCP secrets: `agents.<a>.mcp.<srv>.env_from: [VAR]` / `headers_from: {Header: VAR}` render to `${VAR}` (VAR: POSIX env name `[A-Za-z_][A-Za-z0-9_]*`, any case, e.g. `http_proxy`); hermes-agent interpolates at load from the process env | IMPLEMENTED (b3e282d, 2026-10-30) | hermes_harness.py mcp_servers |
| CFG-CRED-003 | Inline secrets in the user's `~/.hermes/config.yaml` are stripped on render (by design). Declare them in the graph with `env_from` instead | IMPLEMENTED | hermes_harness.py:354-359 |
| CFG-CRED-004 | The local API key for familia nodes comes from `familia_auth.api_key()` (env or local state), never from graph.yaml | IMPLEMENTED | scripts/familia_auth.py |
| CFG-CRED-005 | `HF_TOKEN` is honoured and never printed | IMPLEMENTED | scripts/hf_fetch.py |
| CFG-CRED-006 | Host addresses, logins and ports are not secrets but are private: untracked overlay only (hosts-overlay.md) | IMPLEMENTED | scripts/hosts_overlay.py |
| CFG-CRED-007 | The hermes child env is narrowed to declared `env_from` names | SPEC (known gap: `mcp_env_allowlist` exists but is unused; the child still inherits the full env) | hermes_harness.py mcp_env_allowlist |
| CFG-CRED-008 | Secret files are referenced as `*_file: PATH` (mode 0600, outside the repo) where a tool needs a file rather than env | SPEC | — |
