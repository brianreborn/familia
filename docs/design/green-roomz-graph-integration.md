# Green RoomZ as the Familia graph gateway

**Status:** architecture requirements for the 0.5.0 gateway repair.

## Decision

Every ordinary Familia graph exposes one public gateway owned by Green RoomZ.
The protograph may remain single-model and omit it. `familia start` must not
offer a choice between Green RoomZ and a second public router. Green RoomZ owns
the public listener, caller authentication, protocol surface, model catalog,
and browser UI. Familia's graph remains the source of truth for host placement,
model identity, route aliases, fallback order, and node credentials.

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
   RoomZ listener. The listener serves the Green RoomZ interface and API; no
   public graph-router or raw node listener is required for normal clients.
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

## Native llama.cpp UI path

The llama.cpp b12609 server documentation describes a built-in Llama Chat UI,
OpenAI-compatible chat, Responses and embeddings, Anthropic Messages, and a
configurable `--api-prefix`. These are useful adapter capabilities, not proof
that every installed runtime supports them. The adapter must verify the
runtime-specific contract before exposing a UI path.

`/ui/llama/<alias>/` identifies one graph alias. The gateway serves or proxies
that alias's UI assets and maps the UI's supported backend paths to the same
alias. The route must not let a client use the UI path to escape the graph,
reach arbitrary node ports, or bypass per-node authentication. If a runtime
cannot serve a prefix safely, Green RoomZ serves the static UI and routes its
API requests itself.

## Acceptance

- For each tested graph shape (single node, multiple aliases, fallback, remote
  opt-in, and chain), only the Green RoomZ public listener is needed by a
  client.
- The root loads the Green RoomZ interface; the model-specific llama.cpp UI
  path loads when the selected runtime supports it.
- `/v1/models` lists the full graph catalog and its truthful capabilities.
- Model discovery distinguishes input and output support for text, image,
  video, audio, and spatial/3D media.
- Each advertised protocol is tested end to end with a fake backend and at
  least one live llama.cpp backend. Unsupported protocols fail before the
  request is sent to a model node.
- Wrong/missing caller credentials fail at the public root. Valid caller
  credentials authenticate through the root while per-node credentials remain
  internal.
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
