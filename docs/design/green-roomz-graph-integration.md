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
   RoomZ listener. The root path is a browser UI entrypoint, never REST/API.
   The graph selects the root UI with `gateways.<name>.root_ui`; default to
   `unicorn`, with `llama-ui` and `hermes` as choices. Browser requests at `/`
   are served by the selected UI without changing the browser-visible path.
   Requests to `/` whose `Accept` header excludes HTML receive `406` with a
   pointer to `/v1/`. No public
   graph-router or raw node listener is required for normal clients.
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
7. **Browser UI routes are explicit.** `/unicorn` serves the first-party
   Green RoomZ browser client, `/llama-ui` serves the native llama.cpp UI, and
   `/hermes` serves Hermes Webapp (the desktop renderer in browser mode). The
   selected model comes from the graph catalog inside the UI, not a model name
   or graph alias in the route. `gateways.<name>.root_ui` chooses which UI
   serves `/`; absent a value,
   `/` serves Unicorn. Hermes Desktop remains a native Electron client.
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
| llama.cpp native APIs used by Llama Chat | Put supported engine calls under versioned Green RoomZ routes such as `/v1/engines/llama/<alias>/props`; never expose unversioned backend REST paths. |
| Green RoomZ APIs | Keep catalog, inference, protocol, introspection, and session APIs under `/v1`; reserve `/health` and `/metrics` for operational probes. |

The exact endpoint list and capability names belong in the shared routing
contract, not in separate hand-maintained allowlists in Familia, Green RoomZ,
and each UI. Capability discovery reports the supported operations and
input/output media for each alias. Green RoomZ's top-level task verbs should
cover common work such as `/chat`, `/code`, `/image`, `/video`, `/audio`, and
`/3d` based on those capabilities, without exposing backend or model names as
the user-facing ontology.

## Browser UI routes and versioned API

The graph owns `gateways.<name>.root_ui`; Green RoomZ must not duplicate the
selector in its host manifest. The default is `unicorn`. Supported values are
`unicorn`, `llama-ui`, and `hermes`. Explicit browser routes are:

- `/unicorn` — Green RoomZ first-party chat and file UI.
- `/llama-ui` — native llama.cpp UI; model selection uses the graph catalog in
  the UI and does not appear as a model-specific URL.
- `/hermes` — Hermes Webapp, serving the Desktop renderer in a browser. Hermes
  Desktop itself is a native Electron client.

Familia validates `root_ui` as one of these three values when loading the
graph. A generated runtime manifest carries the validated value to Green
RoomZ but never defines a second selector. An unavailable selected UI makes
graph startup report a configuration/capability error; it never silently
changes the chosen root UI. An unavailable explicit UI path reports that
capability as unavailable without switching to another UI.

For `GET` and `HEAD`, `/` serves the configured UI without redirecting the
browser; absent `root_ui`, it serves Unicorn. The explicit UI aliases serve the
same respective interfaces at `/unicorn`, `/llama-ui`, and `/hermes`. Assets,
refreshes, and API calls must continue to work under each alias path. A root
request whose `Accept` header excludes HTML receives plain `406 Not Acceptable`
with guidance to use `/v1/`. Other root methods return `405 Method Not
Allowed` with `Allow: GET, HEAD`; unknown UI paths return `404`. Neither
resolves to a REST operation.

Inference, catalog, protocol, and model APIs live under `/v1/...`. Health and
metrics are explicit operational probes at `/health` and `/metrics`. Any
engine-specific API needed by a browser UI is versioned and graph-bound; the
gateway must not expose an unversioned backend REST endpoint. UI assets and API
calls stay on the Green RoomZ origin and cannot shadow `/v1` or escape the
selected graph route.

Green RoomZ serves browser HTML and assets at `/` or an explicit UI path. A
browser's data call goes to `/v1`, where Green RoomZ authenticates the caller,
selects a graph model from the request or UI session, and dispatches through
the private graph adapter. The selected model is never inferred from the UI
path. `/llama-ui` may serve a verified local UI bundle or proxy assets from a
private llama.cpp backend; it never exposes a second public listener or lets
the browser call the backend directly. All three UIs must send model identity
through the graph-backed API contract.

The non-sensitive UI shell may load before a caller key is provided so a
browser can display its credential-entry flow. All catalog and inference data
require caller authentication. The browser can enter or change its caller API
key in page memory by default; it is never placed in a URL, page source, logs,
or persistent storage by default. Green RoomZ keeps node credentials internal.
A UI that cannot preserve this boundary is not eligible for a root UI route.
The pre-key shell contains no catalog, prompts, secrets, or node configuration.
Browser UI assets must be served with a restrictive content security policy;
third-party scripts are not loaded into a page holding a caller key.

The llama.cpp UI's engine-specific calls must preserve streaming,
cancellation, catalog identity, and alias binding. Hermes Webapp must use the
same Green RoomZ caller-auth and graph-backed API contract. An option that
cannot meet this contract remains unavailable until adapted.

## Acceptance

- For each tested graph shape (single node, multiple aliases, fallback, remote
  opt-in, and chain), only the Green RoomZ public listener is needed by a
  client.
- Browser `GET /` serves the graph-selected UI without redirecting, defaulting
  to Unicorn; requests whose `Accept` excludes HTML receive `406` directing
  clients to `/v1/`. Other methods at `/` receive `405`.
- `/unicorn`, `/llama-ui`, and `/hermes` resolve only to browser UIs and
  preserve gateway caller authentication and graph routing, including assets,
  refreshes, and API calls.
- Unknown `root_ui` values are rejected during graph validation; an unavailable
  selected UI produces a clear startup error, and an unavailable explicit UI
  path never falls back to a different interface.
- `/v1/models` lists the full graph catalog and truthful capabilities; no REST
  or model API is served at `/`. Protocol and engine-specific APIs are versioned
  under `/v1`; health and metrics are operational probes.
- Model discovery distinguishes input and output support for text, image,
  video, audio, and spatial/3D media.
- Each advertised protocol is tested end to end with a fake backend and at
  least one live llama.cpp backend. Unsupported protocols fail before the
  request is sent to a model node.
- UI shells load without exposing data so browsers can enter a caller key;
  wrong or missing keys fail on catalog and inference APIs. Node credentials
  remain internal.
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
