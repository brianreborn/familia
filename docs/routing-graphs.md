# Routing graphs (graph router)

`scripts/graph_router.py` is one loopback OpenAI-compatible endpoint that routes by
the request's `model` field to a **route**. A route is one of seven shapes, each
a line or two of YAML. Examples for every shape: `examples/routing/`.

```sh
python3 scripts/graph_router.py examples/routing/7-fallback.yaml --check   # validate + print routes
python3 scripts/graph_router.py examples/routing/7-fallback.yaml --port 9940
curl -s 127.0.0.1:9940/v1/chat/completions -d '{"model":"chat","messages":[{"role":"user","content":"hi"}]}'
```

## Config (`version: 1`)

```yaml
version: 1
graph: ../../graph.yaml      # optional: node names resolve from graph.yaml; its aliases become routes
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

Defaults: `kind: chat`, `tools: false`, `remote: false`, router `slash: true`. Nothing
else is needed. A route may share a name only with the node it targets.

| shape | what happens | refused with |
|---|---|---|
| single | forwards to the node | 503 unreachable/loading, 504 read timeout |
| pair | two single routes (e.g. `chat`, `think`); reasoning models are chat backends | as single |
| fallback | tries in order; skips a node only if unreachable or 502/503 | 503 `no node reachable` + `tried[]`; a 4xx is returned from the node that sent it |
| chain | step N's reply is step N+1's user message (`prompt` wraps `{input}`) | 503/502 naming the step; `stream: true` → 400 |
| router | `/label text` picks directly; else the router node must answer one exact label | unknown label without `default` → 502; specialist down → 503 |
| remote | any non-loopback url; requires `remote: true` | config error without it |
| tools | `Authorization: Bearer <node key>`: `key_file`, else the H4 per-port instance key `~/.config/familia/instances/<port>/api-keys` | 503 if no key; nothing is sent |

Always: unknown route → 404 listing routes; chat vs embeddings mismatch → 400; a graph
alias to a planned or slash-only node → 409 naming the node (never dropped). Every
reply has `X-Familia-Route` and `X-Familia-Node` (the node that answered); chains add
`X-Familia-Chain: a>b>c`, routers `X-Familia-Route-Label`.

Timeouts: `FAMILIA_ROUTER_CONNECT_S` (3) to connect, `FAMILIA_ROUTER_TIMEOUT_S` (600) to
read. The router binds 127.0.0.1 only.

## Graph-backed configs

With `graph:`, active nodes come from `graph.yaml`: local url = `127.0.0.1:<port>`;
nodes on other hosts use `hosts.<h>.addr` from `hosts.local.yaml` and must bind a
non-loopback address. Tool-enabled graph nodes (`validate_graph.tool_policy`) get
`tools: true`. Run with `--host-id <graph host>`. Remote graph nodes still need
`nodes: {<name>: {remote: true}}` in the routes file.

## Not covered yet

* Caller auth on the router itself (it is loopback-only); the `:9931` key work is on
  `fix/api-key-passthrough`.
* `start_graph.py` still launches the green-roomz graph-proxy (single node per alias);
  the router is started by hand next to it.
* Streaming through chain/router routes.
