# Agent-Reach (reach tools)

[Agent-Reach](https://github.com/Panniantong/Agent-Reach) gives CLI agents
(Hermes, llama UI / code-bootstraps, OpenClaw, …) one entry point for
login-walled platforms, video transcripts, Chinese platforms, and clean
structured web data. familia pins it in `pins.txt` (**not vendored**):

```
agent-reach	<a19a171…>	https://github.com/Panniantong/Agent-Reach.git	reach tools; not vendored
```

License: **MIT** (`scripts/licenses.py` DECLARED + pin component). Tools enter
through the existing **approval gate** (terminal / MCP). They are **never**
pasted into llama-server. See DESIGN.md § Agent-Reach.

## Graph

```yaml
reaches:
  agent-reach:
    experimental: true
    repo: Panniantong/Agent-Reach
    agents: [hermes]          # which agents may use the reach tools
```

`experimental: true` is required (schema in `scripts/graph_types.py`).

## Enable / status

```sh
python3 scripts/sync_pins.py                  # checkout the pin under ./agent-reach
python3 scripts/agent_reach.py status  # shim → familia_agent_reach.py
python3 scripts/agent_reach.py enable --agent hermes
python3 scripts/agent_reach.py link --agent hermes --dry-run
```

Menu: **Reach tools (Agent-Reach)** → status / enable / disable
(`reach.status`, `reach.enable`, `reach.disable`).

## Hermes bridge

On `scripts/hermes_harness.py` render, if the agent is listed under
`reaches.*.agents`, familia:

1. Symlinks `agent-reach/agent_reach/skill` → `HERMES_HOME/skills/agent-reach`
2. Writes `HERMES_HOME/bin/agent-reach` (runs `python3 -m agent_reach.cli` with
   the pin on `PYTHONPATH` — no copy of the repo)
3. Prepends `HERMES_HOME/bin` to `PATH` for hermes children
4. Drops `HERMES_HOME/agent-reach.mcp.example.json` (doctor/status MCP only)

The agent then uses the **skill** + **terminal** toolset to call
`agent-reach <channel> <action>` (JSON out). Optional channels that need login
still go through Agent-Reach's own browser / login flow — the user logs in;
familia never holds those credentials.

```sh
scripts/hermes.sh --agent hermes --render-only
ls ~/.cache/familia/hermes-hermes/skills/agent-reach
~/.cache/familia/hermes-hermes/bin/agent-reach channels
```

Self-improve / Harness² **cannot** add reaches or widen tools
(`scripts/self_improve.py` gate).

## Llama UI / code-bootstraps

code-bootstraps already has `config/mcp-servers.json`. Merge the example:

```sh
python3 scripts/agent_reach.py mcp-example
# → mcpServers.agent-reach { command: python3, args: [-m, agent_reach.integrations.mcp_server], cwd: <pin> }
```

Or copy `config/mcp-servers.agent-reach.example.json`. That MCP only exposes
doctor/status; channel I/O stays on the CLI + skill (same as Hermes).

## What agents get

| Surface | Default channels (no login) | Optional / experimental |
|---|---|---|
| CLI `agent-reach` | web, youtube, github, v2ex, bilibili | xiaohongshu, reddit, linkedin, boss, xueqiu, twitter, … |
| Skill | routing table + references | — |
| MCP | `get_status` (doctor) | — |

## Related

- Issue #27 (graph node + branding; closed — this doc is the Hermes/llama attach)
- `docs/hermes-plugins.md` (same HERMES_HOME link pattern for plugins)
- `docs/licenses.md`
