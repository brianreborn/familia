# MCP servers for Hermes agents (graph.yaml `agents.<a>.mcp`)

```yaml
agents:
  hermes:
    mcp:
      github:
        command: github-mcp-server
        args: [stdio]
        env_from: [GITHUB_PERSONAL_ACCESS_TOKEN]   # names only; never values
      web:
        url: https://mcp.example/sse
        headers_from: {Authorization: WEB_MCP_TOKEN} # -> "Bearer ${WEB_MCP_TOKEN}"
```

- `scripts/hermes_harness.py` renders these into `HERMES_HOME/config.yaml` `mcp_servers`
  as `${VAR}` refs; hermes-agent interpolates them at load (`tools/mcp_tool_config.py`).
  No secret value is written to disk. The user's `~/.hermes` mcp_servers still have
  secret-looking keys stripped; a graph entry with the same name replaces it.
- Only the declared variables reach MCP subprocesses (hermes builds a filtered env plus
  the entry's `env`), so `env_from` is the allowlist.
- Lean prompt profile keeps `mcp-<name>` toolsets for declared servers.
- Literal `env:` / `headers:` are rejected by the validator.
- Proof test: `tests/test_hermes_mcp.py::test_hermes_agent_loads_rendered_mcp` (runs against
  installed hermes-agent, or `FAMILIA_HERMES_TEST_PY` + `FAMILIA_HERMES_SRC`).
