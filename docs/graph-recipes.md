# Graph recipes: which shape, which keys

Copyable, validated examples live in `examples/graphs/` (kept green by `tests/test_example_graphs.py`).
Validate any of them with `python3 scripts/validate_graph.py examples/graphs/<file>.yaml --no-files`
and preview what `familia start` would do with
`python3 scripts/start_graph.py --graph <file> --host h1 --dry-run --fleet`.

| Shape | Example | Keys that make it work | Routed by | Status today |
|---|---|---|---|---|
| Single node | `single-node.yaml` | `nodes`, one `aliases` entry, `gateways` | green-roomz graph-proxy (alias = model name) | works |
| Specialists fan-out | `fanout-specialists.yaml` | one alias per node | client picks alias; no auto-classifier | works (manual pick only) |
| Light -> heavy chain | `escalation-chain.yaml` | `escalates_to`, `escalation.mode` | `scripts/escalation_proxy.py` (`hermes.sh --escalate`) | suggest/auto works with mock upstreams; green-roomz hookup planned (#39) |
| Tools on a node | `explicit-tools.yaml` | `server_tools` (list or `all`), `tool_route` + `tool_capable: false` | llama-server `--tools`; nexus forward is PR #251 | works; set `server_tools` explicitly (#264 changes the implicit default to read-only) |
| Two hosts | `two-host.yaml` | second host, runtime `hosts`, a non-local `transports` entry | each host's own `familia start` | per-host only; aliases to another host are omitted, never proxied |
| Fallback when a node is down | `escalation-chain.yaml` | `escalates_to` | escalation proxy falls back to the light node (tests/test_escalation_proxy.py) | unreachable targets are dropped; no target -> `decision: none` |

## Gotchas the validator now warns about
- An alias to a node whose **model** role is not chat/coder (e.g. `reasoning`) validates but
  `familia start` refuses it. `nodes.<n>.role` does not change this; the launcher reads the model role.
- `tool_route` on a node that is itself tool-capable does nothing for tools; add `tool_capable: false`.

## Not available yet (SPEC in docs/config/routing-spec.md)
- An alias naming several nodes with a policy (`competing | tandem | escalate | first-active`), CFG-SPEC-ALIAS-001.
- A pipeline (output of node A fed to node B). `councils: mode: cascade` validates but nothing runs it.
