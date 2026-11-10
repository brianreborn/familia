# Routing, tools, agents, escalation: config requirements

Sources: the #199 catalogue, `planned-state-spec.md`, `router-requirements-notes.md` and `pentest-mcp-tools-audit.md` (Routing Test Designer notes).
Tests: `tests/test_router_199.py` (draft PR #200), `tests/test_config_spec.py` (this PR).
**SPEC** = required, not implemented yet. **IMPLEMENTED** = in code at the pointer.

## Planned state (CFG-SPEC-PLAN)
A planned node is **excluded from automatic routing only**. It is never dropped or banned, and you reach it explicitly with a slash command (`/pentest`, `/<alias>`, `/<TYPE>`).

| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-SPEC-PLAN-001 | `nodes.<n>.status` ∈ {planned, active}; the sub-state is **derived at load, never written**: `ready` (weights READY), `missing-weights`, `unverified-sha`, `sha-mismatch`, `remote` | SPEC (states derivable today via guardian_ready.check_weight READY/MISSING/UNMEASURED/MISMATCH) | scripts/guardian_ready.py:167-216 |
| CFG-SPEC-PLAN-002 | Auto-route eligibility = status active ∧ TYPE not slash-only ∧ policy allows | SPEC | — |
| CFG-SPEC-PLAN-003 | Slash on `planned/ready` (local) lazily starts the node with the same argv and RAM gate; answers 503 `starting` until ready | SPEC | — |
| CFG-SPEC-PLAN-004 | Slash on missing-weights / unverified-sha → 409 with node, TYPE, state and the single next command. **No fetch-on-switch.** sha-mismatch → hard refuse. An explicit `/<alias> fetch` with operator confirm may be added | SPEC | — |
| CFG-SPEC-PLAN-005 | An alias to a planned node is valid, kept in the manifest with `status/substate/auto:false/slash:true`, and never silently dropped | SPEC (today dropped: start_graph.py:147) | — |
| CFG-SPEC-PLAN-006 | Transitions only by operator command or graph edit: missing-weights →fetch→ unverified-sha →measure→ ready →#119 gate + edit→ active. A slash request never changes status | SPEC (activate_guardian_weights.py implements fetch/measure for guardian) | scripts/activate_guardian_weights.py |
| CFG-SPEC-PLAN-007 | Errors the user sees (exact texts): auto slash-only → 404 `X is slash-only; use /X`; not ready → 409 `<node> (<type>) is planned/<substate>. Next: <cmd>`; confirm missing → 403; remote → 409 naming the host | SPEC | — |

## Gateway role exposure (CFG-SPEC-GW)
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-SPEC-GW-001 | The manifest backend `kind` covers chat, embedding, **guardian, pentest, decision**. Slash-only TYPEs are reachable by explicit slash or exact alias, never by auto TYPE match | SPEC (today refused: start_graph.py:169; graph-proxy.mjs:27) | — |
| CFG-SPEC-GW-002 | One router per host with an active node, keyed by TYPE; host = placement only | SPEC | — |
| CFG-SPEC-GW-003 | Manifest entry schema: `{kind, type, url|null, status, substate, auto, slash, seatbelt?}`; `GET /v1/models` lists all of them | SPEC (today `{kind,url}`: start_graph.py:175-178) | — |
| CFG-SPEC-GW-004 | An unknown TYPE/alias → 404 listing valid slash tokens; never a silent default | IMPLEMENTED for unknown alias (graph-proxy 404); SPEC for the token list | green-roomz src/graph-proxy.mjs:131-135 |

## Alias as a list of nodes (#150) (CFG-SPEC-ALIAS)
| ID | Requirement | Status |
|---|---|---|
| CFG-SPEC-ALIAS-001 | `aliases.<a>.node` may be a list of nodes (same role, any engine/runtime), with `policy: competing \| tandem \| specialized \| escalate \| first-active` (default `first-active`) | PARTIAL: an ordered list (first-active) is implemented (graph_types `noderefs`, served by scripts/graph_router.py); `policy:` is SPEC |
| CFG-SPEC-ALIAS-002 | All listed nodes have one TYPE; mixed TYPEs are a validation error | SPEC |
| CFG-SPEC-ALIAS-003 | Planned members are slash-only members; auto picks only active members | SPEC |

## Explicit `--tools` per TYPE (CFG-SPEC-TOOLS)
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-SPEC-TOOLS-001 | Every llama-server process (graph node, `familia start`/systemd, Termux `with-fleet`, all via server_args) gets an explicit per-TYPE tools decision | IMPLEMENTED | validate_graph.py server_args/tools_argv |
| CFG-SPEC-TOOLS-002 | Per-TYPE default `tool_policy` (coder = all; chat/general = read set; others none). Superseded by TOOLS-007..010 (capability-based). A present `server_tools` key stays authoritative | SUPERSEDED | see CFG-SPEC-TOOLS-007 |
| CFG-SPEC-TOOLS-003 | A node override (`server_tools`) needs `override_reasons.server_tools` | SPEC | — |
| CFG-SPEC-TOOLS-004 | Loopback bind required when any host-exec tool is on. Loopback is `localhost` (literal, any case, no DNS), the IPv4 loopback prefix (127/8), `::1` / `[::1]`, and IPv4-mapped `::ffff:` of those loopback addresses. The unspecified IPv4 and IPv6 binds (`::` and IPv4 all-zeros) and other DNS names are not loopback. `escalation_proxy.node_url` uses that same check for a remote bind | IMPLEMENTED | validate_graph.py `_loopback` (ipaddress); graph_types.py check_node; escalation_proxy.py node_url |
| CFG-SPEC-TOOLS-005 | guardian/pentest/defender reject a `server_tools` grant (`all`/list) (it would bypass the pentest mode ladder); the launcher's `tool_policy` also fails closed to none for these TYPEs. Role names are compared after NFKC + casefold, so `Guardian` / `GUARDIAN` / fullwidth forms fail closed the same way in `tool_policy`, Hermes, the proxy, and graph_types | IMPLEMENTED | graph_types.py check_node (reject); validate_graph.py normalize_role / tool_policy; hermes_harness.py _node_role; tests/test_routing_toolroute.py |
| CFG-SPEC-TOOLS-006 | `server_tools: []` / `none` / `false` is an explicit opt-out: accepted by validation on any TYPE and any bind (loopback check applies only to grants), and emits no `--tools` flag. Hermes `route_tools` returns `none`; `escalation_proxy.tool_target` also refuses to forward from an opted-out source (#340) | IMPLEMENTED | graph_types.py check_node; validate_graph.py tool_policy; hermes_harness.py route_tools; escalation_proxy.py tool_target; tests/test_graph_types.py; tests/test_routing_toolroute.py |
| CFG-SPEC-TOOLS-007 | Capability-based default: any node whose model can use tools gets the read-only set (`read_file,file_glob_search,grep_search,get_info`) when `server_tools` is absent; shell/write tools (`exec_shell_command`, `write_file`, `edit_file`) only via an explicit `server_tools` (H4). Every tool-enabled server is launched with `--api-key-file` (per-instance key on every endpoint). Capability = `nodes.<n>.tool_capable` > `models.<m>.tool_calls` > TYPE presumption (coder/chat/general/reasoning yes; embed/decision/vision/diffusion no) | IMPLEMENTED | validate_graph.py tool_capable/tool_policy |
| CFG-SPEC-TOOLS-008 | The default grant applies only on a loopback bind (host-exec safety; bind matrix as TOOLS-004, via `ipaddress`, no DNS resolution); off loopback a grant needs explicit `server_tools` (still subject to TOOLS-004). Hermes `route_tools` agrees: an off-loopback directly tool-capable node with no `server_tools` key is not `direct` (#345); it may still use an explicit `tool_route` (TOOLS-009 opt-in), otherwise `none`. Discovery / resident-peer nexus is not consulted, so rebinding to a non-loopback address cannot implicitly forward. Loopback default remains `direct` | IMPLEMENTED | validate_graph.py tool_policy / `_loopback`; hermes_harness.py route_tools; tests/test_routing_toolroute.py; tests/test_routing_offloopback_explicit_route.py; tests/test_config_consumers.py |
| CFG-SPEC-TOOLS-009 | Tool-capable via nexus routing: `nodes.<n>.tool_route: <node>` marks a node tool-capable when its target is a directly capable, non-fail-closed, unrouted node with a non-empty grant (one hop). The routed node's grant is exactly `tool_policy(target)`; the routed node's own server gets no `--tools` (tools run on the target). An explicit `server_tools` opt-out on either side wins. An off-loopback source without `server_tools` reaches tools only through an explicit `tool_route` (not Hermes discovery). A source that is itself directly tool-capable (and so launches with its own `--tools`) stays direct: `escalation_proxy.tool_target` does not forward, agreeing with Hermes `route_tools` (#340). The proxy also refuses a source whose `tool_policy` is empty, even when `server_tools` is absent. Proxy hops are unencrypted: `node_url` is an http URL with no TLS, both for a same-host dial and for a remote host-address dial. A remote loopback bind (TOOLS-004 matrix) is not dialed and needs a tunnel | IMPLEMENTED | validate_graph.py tool_route/tool_policy/tools_argv; hermes_harness.py route_tools; escalation_proxy.py tool_target / node_url; tests/test_routing_toolroute.py; tests/test_routing_offloopback_explicit_route.py |
| CFG-SPEC-TOOLS-010 | Route and tool target come only from validated graph config, never from model output or requests (including hostile `X-Familia-*` headers, which must never widen tool access). `graph_types` rejects `tool_route` on guardian/pentest/defender, to a fail-closed target, to itself, unknown, or multi-hop; guardian/pentest/defender stay denied via nexus. The escalation proxy stamps `X-Familia-Tool-Hop` on a forward and refuses re-entry (hop ≥ 1) with 502 so a forwarded request cannot loop or bypass policy, including when the target URL is the proxy itself. Every inbound `X-Familia-*` request header is stripped before the upstream request; the proxy then sets only `X-Familia-Request-Id` and, on an actual tool forward, `X-Familia-Tool-Hop` | IMPLEMENTED | graph_types.py check_node; escalation_proxy.py rewrite / outbound_headers / `_fwd`; tests/test_routing_toolroute.py; tests/test_config_consumers.py |

## Agents: MCP, toolsets, prompt profile (CFG-SPEC-AGENT / CFG-SPEC-MCP)
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-SPEC-MCP-001 | `agents.<a>.mcp.<srv>` declares MCP servers (command\|url, args, env_from, headers_from, tools, enabled) | IMPLEMENTED (b3e282d) | graph_types.py:318-333 |
| CFG-SPEC-MCP-002 | Secrets are rendered as `${VAR}` references only; the value comes from the environment at hermes load | IMPLEMENTED (b3e282d) | hermes_harness.py mcp_servers() |
| CFG-SPEC-MCP-003 | Declared MCP toolsets (`mcp-<srv>`) survive the lean trim | IMPLEMENTED (b3e282d) | hermes_harness.py lean_toolsets(keep=) |
| CFG-SPEC-MCP-004 | The hermes child env is narrowed to the declared `env_from` names (`mcp_env_allowlist`) | SPEC (helper exists, unused; the child inherits the full env) | hermes_harness.py:438 |
| CFG-SPEC-MCP-005 | An end-to-end test with hermes-agent installed proves tool discovery and invocation | IMPLEMENTED when hermes-agent present (skips otherwise) | tests/test_hermes_mcp.py |
| CFG-SPEC-AGENT-001 | `agents.<a>.aliases.main/auxiliary` may name TYPEs; the harness routes via the host router instead of pinning one alias | SPEC | hermes_harness.py:230 owns smart_model_routing |
| CFG-SPEC-AGENT-002 | `agents.<a>.toolsets: [..]` explicit selection; `prompt_profile: auto` trims to lean on phones or ram_mib < 8192 (**documented auto-trim**) and must print a warning naming the dropped toolsets | SPEC (trim IMPLEMENTED, silent) | hermes_harness.py prompt_profile/lean_toolsets |
| CFG-SPEC-AGENT-003 | Lean toolsets = terminal, file, todo, clarify, skills + declared `mcp-*`; LEAN_AUX_DROP aux tasks dropped; `mcp` aux kept | IMPLEMENTED | hermes_harness.py:233-246 |

## Escalation policy (CFG-SPEC-ESC)
| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-SPEC-ESC-001 | `nodes.<n>.escalates_to` + `escalation.mode` off\|suggest\|auto (default suggest); first cross-host escalation needs recorded consent | IMPLEMENTED | escalation.py:36-61,160-180 |
| CFG-SPEC-ESC-002 | hermes graph mode auto-enables the proxy when the main node can escalate | IMPLEMENTED | hermes_modes.py:218-221 |
| CFG-SPEC-ESC-003 | Minimal path: the default agent's main TYPE has ≥1 **active** light→heavy edge in suggest mode | SPEC (today every escalating node is planned) | graph.yaml |
| CFG-SPEC-ESC-004 | **Never** escalate into guardian/pentest nodes; validation rejects such `escalates_to` | SPEC | escalation.py check_node_escalation |
