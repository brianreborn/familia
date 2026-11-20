# Graph recipes: which shape, which keys

Copyable, validated examples live in `examples/graphs/` (kept green by `tests/test_example_graphs.py`).
Validate any of them with `python3 scripts/validate_graph.py examples/graphs/<file>.yaml --no-files`
and preview what `familia start` would do with
`python3 scripts/start_graph.py --graph <file> --host h1 --dry-run --fleet`.

| Shape | Example | Keys that make it work | Routed by | Status today |
|---|---|---|---|---|
| Single node | `single-node.yaml` | `nodes`, one `aliases` entry, `gateways` | `scripts/graph_router.py` (alias = model name); `router: false` -> green-roomz graph-proxy | works |
| Specialists fan-out | `fanout-specialists.yaml` | one alias per node | client picks alias; no auto-classifier | works (manual pick only) |
| Light -> heavy chain | `escalation-chain.yaml` | `escalates_to`, `escalation.mode` | `scripts/escalation_proxy.py` (`hermes.sh --escalate`) | suggest/auto works with mock upstreams; green-roomz hookup planned (#39) |
| Tools on a node | `explicit-tools.yaml` | `server_tools` (list or `all`), `tool_route` + `tool_capable: false` | llama-server `--tools`; nexus forward is PR #251 | works; set `server_tools` explicitly (#264 changes the implicit default to read-only) |
| Two hosts | `two-host.yaml` | second host, runtime `hosts`, a non-local `transports` entry | each host's own `familia start` | per-host only; aliases to another host are omitted, never proxied |
| Fallback when a node is down | `fallback-list.yaml` | `aliases.<a>.node: [first, backup, ...]` | `scripts/graph_router.py` (the default gateway) | works; a node is skipped only when unreachable or 502/503 |
| Escalate light -> heavy | `escalation-chain.yaml` | `escalates_to` | escalation proxy falls back to the light node (tests/test_escalation_proxy.py) | unreachable targets are dropped; no target -> `decision: none` |
| Remote node in an alias | `two-host.yaml` + `remote: true` | `aliases.<a>.remote: true`, `hosts.<h>.addr`, node `bind` not loopback | `scripts/graph_router.py` | opt-in only; without all three the alias is omitted |
| Cascade council (A's reply -> B) | `councils.<c>: {mode: cascade, agents: [a, b]}` | each agent's `main` alias, in order | `scripts/graph_router.py` chain route named `<c>` | works when every agent's main alias is on the same local gateway, else `familia start` refuses |
| Classifier, chain, tool keys | `router/*.yaml` | graph_router routes file (below) | `scripts/graph_router.py` by hand | works; not expressible in graph.yaml yet |

## Gotchas the validator now warns about
- An alias to a node whose role (`nodes.<n>.role`, else the model role) is not chat, coder, general or reasoning (e.g. `vision`) validates but
  `familia start` refuses it. chat, coder, general and reasoning nodes are routed as chat.
- `tool_route` on a node that is itself tool-capable does nothing for tools; add `tool_capable: false`.

## Which gateway process `familia start` runs
- Default: `scripts/graph_router.py` on the gateway port for every gateway. `--dry-run` prints
  `via graph_router (caller auth: <key file>; /health public)`.
- `gateways.<g>.router: false`: green-roomz `graph-proxy` instead (dry-run: `via graph-proxy`), as long as every
  alias is one local node. Aliases with a fallback list or a remote member still need graph_router.
- Caller auth (everything except `/health`): `Authorization: Bearer <key>` or `X-Api-Key: <key>`, else 401.
  The key is the per-port instance key `~/.config/familia/instances/<port>/api-keys` (Windows: under `%APPDATA%`),
  created 0600 on first start and never rotated; unreadable -> the router refuses to start. On 9931 that is the
  file familia clients already read (`familia_auth.api_key()`), so they keep working. The caller key is never
  forwarded to nodes; tool nodes get their own key.
- Node servers follow the same rule (DESIGN.md Security, CFG-GRAPH-NODES-112): `validate_graph.py --args`
  always includes `--api-key-file`, tools or not. Auth is not a graph.yaml field. Localhost without a
  key is only for the named exceptions in DESIGN.md; a recipe or example graph must not assume an open
  listener. New graphs (including a protograph recipe when that skill lands, #399) start from this rule.
- Down node: graph_router answers 503 within the 3 s connect bound (`FAMILIA_ROUTER_CONNECT_S`; a refused
  port measured 0.001 s on :9931). graph-proxy (`router: false`) retries ECONNREFUSED for 180 s before a 502
  (measured 181.4 s, green-roomz b2a8eac; fixed in its graph-proxy, not settable from the manifest).

## graph_router routes files (`examples/graphs/router/`)

```sh
python3 scripts/graph_router.py examples/graphs/router/fallback.yaml --check   # validate + print routes
python3 scripts/graph_router.py examples/graphs/router/fallback.yaml --port 9940
# key: first non-comment line of ~/.config/familia/instances/9940/api-keys
curl -s 127.0.0.1:9940/v1/chat/completions -H "Authorization: Bearer $KEY" \
  -d '{"model":"chat","messages":[{"role":"user","content":"hi"}]}'
```

```yaml
version: 1
graph: ../../../graph.yaml   # optional: node names resolve from graph.yaml; its aliases become routes
nodes:                       # name -> url, or a map
  a: http://127.0.0.1:8081
  t: {url: http://127.0.0.1:8082, tools: true}                       # sends t's own key
  r: {url: http://10.0.0.5:8080, remote: true, key_file: ~/.config/familia/remote-keys/r}
  e: {url: http://127.0.0.1:8083, kind: embedding}
routes:                      # omit entirely: every node is its own route
  single: a
  fallback: [a, t]                                  # or {fallback: [...]}
  chain: {chain: [a, {node: t, prompt: "fix: {input}"}, a]}
  ask: {router: a, routes: {code: t, far: r}, default: a}   # default optional
```

Defaults: `kind: chat`, `tools: false`, `remote: false`, router `slash: true`. A route may share a
name only with the node it targets. A chat + reasoning pair is just two routes (or two graph aliases).

| shape | what happens | refused with |
|---|---|---|
| single | forwards to the node | 503 unreachable/loading, 504 read timeout |
| fallback | tries in order; skips a node only if unreachable or 502/503 | 503 `no node reachable` + `tried[]`; a 4xx is returned from the node that sent it |
| chain | step N's reply is step N+1's user message (`prompt` wraps `{input}`) | 503/502 naming the step; `stream: true` streams only the final step (earlier steps run non-streamed) |
| router | `/label text` picks directly; else the router node must answer one exact label | unknown label without `default` -> 502; specialist down -> 503 |
| remote | any non-loopback url; requires `remote: true` | config error without it |
| tools | `Authorization: Bearer <node key>`: `key_file`, else the node port's instance key | 503 if no key; nothing is sent |
| remote + key | the bearer key travels over plain `http://` (L14, #304); startup prints a WARNING per such node | warning only; tunnel it (SSH) or keep the node loopback |

Always: no/wrong caller key -> 401; unknown route -> 404 listing routes; chat vs embeddings
mismatch -> 400; a graph alias to a planned or slash-only node -> 409 naming the node. Replies carry
`X-Familia-Route` and `X-Familia-Node`; chains add `X-Familia-Chain`, routers `X-Familia-Route-Label`.
Timeouts: `FAMILIA_ROUTER_CONNECT_S` (3), `FAMILIA_ROUTER_TIMEOUT_S` (600). Binds 127.0.0.1 only.

## Not available yet (SPEC in docs/config/routing-spec.md)
- Alias policies other than ordered fallback (`competing | tandem | escalate`), CFG-SPEC-ALIAS-001.
  An ordered list (= `first-active`) works today.
- Classifier routes and chains declared in graph.yaml (use a router/ routes file).
- Streaming through chain/router routes.
- `councils: mode: quorum` validates but nothing runs it.
