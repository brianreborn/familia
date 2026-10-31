# nexus tool-forward (local branch, not pushed)

## Gap vs #243
- #243 added `tool_capable` / `tool_route` / `tool_policy` / `tools_argv` in `scripts/validate_graph.py`.
  That is launch-time only: it decides which `--tools` flag each llama-server gets.
- `scripts/nexus/nexus.py` is the SSH artifact hub (register/peers/put/ls/get). It never carries chat
  traffic, so it was the wrong place for a runtime forward. The HTTP chat path is
  `scripts/escalation_proxy.py` (hermes -> 127.0.0.1 proxy -> node).
- Before this branch, nothing at runtime read `tool_route`: a routed-only node launched without `--tools`
  and tool requests that landed on it went nowhere.
- No node in `graph.yaml` sets `tool_route`; no model sets `tool_calls`.

## This branch
- `escalation_proxy.tool_target(g, node)` wraps `validate_graph.tool_route` (same validation: target must
  exist, be tool-capable, not be guardian/pentest/defender, not be routed itself, and have a non-empty policy).
- `Escalator.rewrite()`: if the request has `tools` and the current node has a validated route, the whole
  request goes to the target's URL/alias. The target runs the chat+tools loop under its own `--tools`
  (tool_policy). If the target is unreachable (remote loopback bind), the request stays where it is.
- Tests: 3 new ones in `tests/test_escalation_proxy.py`.

## Example (NOT applied to graph.yaml)
```yaml
nodes:
  light:  { ..., tool_route: coder }   # tool-bearing requests -> coder
  coder:  { ..., bind: 127.0.0.1 }     # loopback + tool-capable -> --tools all
```

## Not changed
- graph.yaml (angel/phones), nexus.py, launcher/validate_graph, live servers.
- Option (b), running individual tool_calls on the target, was not built. It would mean a new tool-exec endpoint.
