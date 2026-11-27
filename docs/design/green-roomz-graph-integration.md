# Green RoomZ as the Familia graph gateway

**Status:** architecture requirements for the 0.5.0 gateway repair.

## Decision

Every ordinary Familia graph exposes one public gateway owned by Green RoomZ.
The protograph may remain single-model and omit it. `familia start` must not
offer a choice between Green RoomZ and a second public router. Green RoomZ owns
the public listener, caller authentication, protocol surface, model catalog,
and browser UI. Familia's graph remains the source of truth for host placement,
model identity, route aliases, fallback order, node credentials, and the selected
root UI.

Graph routing becomes a Green RoomZ backend adapter. It may reuse the current
graph-router implementation internally while that adapter is proven, but the
graph router is never a second public entry point and never owns a separate
caller credential or browser UI. The adapter is selected from the graph's
declared topology; users do not configure the internal architecture.

## Current mismatch

The current `familia start` path chooses between two public processes:

- `scripts/graph_router.py` handles graph aliases and fallback/chain routing,
  but only implements `/v1/models`, chat completions, and embeddings, plus a
  small standalone chat page.
- Green RoomZ owns its landing page, Unicorn UI, agent behavior, and a wider
  protocol surface, but its `graph-proxy` only accepts one local backend per
  alias and handles chat completions and embeddings.

This means no current process is both the complete Green RoomZ application
and the complete Familia graph gateway. The issue is architectural composition,
not a missing toggle in `graph.yaml`.

## Requirements

1. **One public root.** A normal graph has one externally reachable Green
   RoomZ listener. `/` is a browser UI entrypoint, never a REST/API endpoint.
   The graph selects the root UI with `gateways.<name>.root_ui`; default to
   `unicorn`, with `llama-ui:<alias>` and `hermes-webapp` as choices. A
   non-HTML request to `/` receives a plain `406 Not Acceptable` pointing to
   `/v1/`. No public graph-router or raw node listener is required for normal
   clients.
2. **One graph catalog.** `GET /v1/models` and model detail endpoints report
   every declared routable graph alias, including remote, fallback, and
   unavailable entries, with truthful per-protocol and per-modality
   capabilities. A model name is never inferred from a backend product name.
3. **Preserve graph semantics.** Alias selection, ordered fallback, bounded
   chains, fan-out, remote opt-in, node health, context limits, and per-node
   credentials keep their Familia graph meaning. Green RoomZ must not silently
   flatten or reorder these semantics.
4. **One caller-auth boundary.** The public Green RoomZ listener authenticates
   callers. The adapter is private to that gateway. Caller credentials are
   never forwarded to model nodes; node credentials are never returned to
   clients. Protocol adaptation shares the same credential store.
5. **Protocols are adapter capabilities.** The gateway advertises and accepts
   a protocol only when both the selected route and its backend adapter support
   it. Unknown routes return a clear error. Streaming, tool calls, structured
   output, multimodal input/output, and cancellation must preserve their
   semantics through the adapter or be explicitly refused before dispatch.
   Capability records separate input from output and represent text, still
   image, video, audio, and spatial/3D media as distinct types. A model that can
   inspect images is not thereby declared able to generate images, video, or
   3D assets.
6. **No duplicated routing authority.** Green RoomZ owns request lifecycle,
   sessions, and user-facing behavior. Familia graph declarations own backend
   placement and graph topology. An adapter translates between them; it must
   not maintain a competing model catalog or policy file.
7. **Native model UI is routed.** Green RoomZ serves its own interface at `/`.
   A native llama.cpp chat UI, when enabled for a graph alias, is exposed at a
   model-specific path such as `/ui/llama/<alias>/`. Its static assets and
   backend API calls stay on the same origin and pass through Green RoomZ
   authentication and graph routing. It must not connect directly to a node.
8. **No hidden runtime assumptions.** UI and API capabilities are derived from
   the installed runtime's verified adapter support. A versioned flag table or
   a tested runtime capability record is required before using options such as
   llama.cpp's `--api-prefix`.
9. **One lifecycle.** `familia start`, status, stop, and restart manage the
   public Green RoomZ process and its adapter as one graph service. Startup
   verifies the public gateway, not merely a backend health endpoint.
10. **Compatibility is not a constraint.** Before 1.0, remove the old public
    router mode and stale configuration as soon as the Green RoomZ path meets
    acceptance; do not preserve duplicate modes for compatibility.

## Protocol inventory to implement and verify

The adapter registry must cover the APIs Familia elects to expose, including
at minimum:

| Surface | Required behavior |
| --- | --- |
| OpenAI chat/completions and Responses | Route by public alias; preserve stream, tool, JSON-schema, usage, and cancellation behavior. |
| OpenAI completions, embeddings, rerank, moderation, images, and audio | Advertise only supported backend capabilities and preserve request/response types. |
| Anthropic Messages | Preserve system blocks, tools, streaming events, and errors; no silent conversion loss. |
| llama.cpp native APIs used by Llama Chat | Cover only documented routes needed by the UI (for example `/props`, `/slots`, `/tools`, and monitoring); scope node-specific operations to the alias path. |
| Green RoomZ APIs | Keep Green RoomZ health, route/model introspection, sessions, and its browser client at the canonical origin. |

The exact endpoint list and capability names belong in the shared routing
contract, not in separate hand-maintained allowlists in Familia, Green RoomZ,
and each UI. Capability discovery reports the supported operations and
input/output media for each alias. Green RoomZ's top-level task verbs should
cover common work such as `/chat`, `/code`, `/image`, `/video`, `/audio`, and
`/3d` based on those capabilities, without exposing backend or model names as
the user-facing ontology.

## Browser UI and versioned API

The graph selects one browser UI at the Green RoomZ origin. `unicorn` is the
first-party default; `llama-ui:<alias>` selects a graph alias, and
`hermes-webapp` serves Hermes' desktop renderer in browser mode. Native Hermes
Desktop is an Electron client, not a web page. UI choice is graph configuration,
not a second Green RoomZ manifest setting.

`GET` and `HEAD /` serve the configured browser UI only when the client accepts
HTML. Other root requests receive a plain `406 Not Acceptable` with guidance to
use `/v1/...`; the root never aliases an API or model endpoint. All public
inference, catalog, protocol, and model APIs use `/v1/...`. Health and metrics
remain explicit operational endpoints. UI asset and engine-specific calls must
be routed through Green RoomZ and namespaced so they cannot shadow `/v1` or
escape the selected graph alias.

The selected UI uses the Green RoomZ origin and caller-auth boundary. A browser
can enter or change its caller API key in page memory by default; it is never
placed in a URL, page source, logs, or persistent storage by default. Every UI
must pass the caller key to Green RoomZ, which keeps node credentials internal.
A UI that cannot preserve this boundary is not eligible for `root_ui`.

For `llama-ui:<alias>`, Green RoomZ serves or proxies the native UI assets and
maps its engine-specific calls through the selected graph alias. Any native
llama.cpp endpoints outside `/v1` are exposed only through an explicitly
versioned Green RoomZ adapter route, never as unversioned public REST. The UI
must preserve streaming, cancellation, model catalog identity, and auth. If the
pinned runtime cannot be mounted and routed safely, that UI option remains
unavailable until a Green RoomZ-owned frontend can reproduce the needed
behavior.

## Acceptance

- For each tested graph shape (single node, multiple aliases, fallback, remote
  opt-in, and chain), only the Green RoomZ public listener is needed by a
  client.
- `/` serves the graph-selected browser UI for HTML clients; non-HTML root
  requests receive 406 guidance to `/v1/`.
- Unicorn, a model-selected llama.cpp UI, and Hermes Webapp are selectable only
  when they preserve the same-origin caller-auth and graph-routing contract.
- `/v1/models` lists the full graph catalog and truthful capabilities; no REST
  or model API is served at `/`. All protocol endpoints are versioned under
  `/v1`, with health/metrics limited to explicit operational routes.
- Model discovery distinguishes input and output support for text, image,
  video, audio, and spatial/3D media.
- Each advertised protocol is tested end to end with a fake backend and at
  least one live llama.cpp backend. Unsupported protocols fail before the
  request is sent to a model node.
- Wrong/missing caller credentials fail at the public gateway. Browser UIs
  can provide a caller key without persisting or exposing it; per-node
  credentials remain internal.
- Tool round trips, SSE streaming, cancellation, and errors traverse the same
  public root. No user-facing client needs a node address or a second router
  port.
- Graph startup, health, stop, and restart operate on the composed service and
  report backend and adapter failures separately.

## Research sources

- [llama.cpp b12609 server README](https://github.com/ggml-org/llama.cpp/blob/b12609/tools/server/README.md)
- [llama.cpp Llama Chat README](https://github.com/ggml-org/llama.cpp/blob/master/ui/apps/chat/README.md)

The upstream server README is pinned here to the b12609 source revision used
by the current Familia runtime pin. The current Llama Chat README is used for
the static UI deployment model; runtime builds still require local capability
verification.
