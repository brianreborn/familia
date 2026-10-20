# Official Hermes Agent plugins (#92)

familia serves local models through `scripts/hermes_harness.py`, which renders a
private `HERMES_HOME` under `~/.cache/familia/hermes-<agent>`. Official /
portable [Agent Plugins v1](https://agent-plugins.org) packages (MCP + Skill),
including Nous Research's **rea** plugin, install into `~/.hermes/plugins/`.

## Bridge

`agents.<name>.plugins` in `graph.yaml`:

```yaml
agents:
  hermes-lab:
    plugins: [rea]    # or ["*"] for every directory under ~/.hermes/plugins
```

On render, familia **symlinks** each named plugin from `~/.hermes/plugins/<name>`
into the rendered home's `plugins/`. It never downloads, never enables a plugin
the user has not installed, and never copies secrets.

```sh
# once, in the real ~/.hermes (needs Node for REA's MCP server):
hermes plugins install rea
hermes plugins enable rea

# then opt the familia agent in via graph.yaml and:
scripts/hermes.sh --agent hermes-lab --render-only
ls ~/.cache/familia/hermes-hermes-lab/plugins/
```

## REA notes

- Catalog: https://hermes-agent.nousresearch.com/docs/plugins/rea
- Package: `mcp.json` (npx `rea-agents@6.7.0` stdio) + skills
  `reverse-engineer-anything`, `crash-triage`
- Needs Node.js 22.19+/24.11+/26+ on PATH for the MCP server. Decompilers
  (Ghidra, …) are optional and bring-your-own.
- REA registers ~207 tools behind Hermes' on-demand tool search; they are not
  dumped into the visible tool list (important for lean prompts, #89).
- Some REA tools can run or change targets; the bundled skill tells the agent
  to ask first. familia does not relax that.

## Harness² / self-improve

Self-improve **cannot** add plugins, tools, or widen permissions
(`scripts/self_improve.py` gate; `docs/harness2.md`). Plugin opt-in is only via
`graph.yaml` edited by a human. Equivalent check under Harness²: the same local
model endpoint serves both hermes and Harness² targets; enabling `rea` for an
agent does not change Harness²'s editable file surface.

## Why a plugin might not run

| Reason | What to do |
|---|---|
| Not installed under `~/.hermes/plugins` | `hermes plugins install rea` |
| Agent has no `plugins:` list | Add `plugins: [rea]` under the agent |
| Node missing | Install a supported Node; REA's MCP will not start without it |
| Engine (Ghidra, …) missing | Optional; static JS/metadata tools still work |
