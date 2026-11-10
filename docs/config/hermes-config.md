# Generated hermes config (`~/.cache/familia/hermes-<agent>/config.yaml`)

Producer: `scripts/hermes_harness.py` render() (from graph.yaml `agents`, `aliases`, `nodes` + user `~/.hermes/config.yaml`). Consumer: hermes-agent.
**Never edit by hand.** It is rewritten on every launch.

| ID | Requirement | Status | Pointer |
|---|---|---|---|
| CFG-HERMES-001 | Harness-owned keys (`model, auxiliary, compression, custom_providers, providers, smart_model_routing, fallback_model`) never come from the user config | IMPLEMENTED | hermes_harness.py:451 |
| CFG-HERMES-009 | Local-only defaults are open-weight: aux tasks and `model` use `provider: custom` on the local node; `auxiliary.free_only` plus `openrouter_model: disabled` skip the stock OpenRouter hosted fallback; `providers` / `custom_providers` are empty; `fallback_model` and `smart_model_routing` stay omitted (disabled). `FAMILIA_HERMES_ALLOW_CLOUD=1` is the explicit opt-in for upstream cloud defaults | IMPLEMENTED | hermes_harness.py:1254-1264; tests/test_hermes_upstream_compat.py::test_aux_defaults_are_open_weight_not_hosted |
| CFG-HERMES-002 | User keys are copied minus secret-named keys (`strip_secrets`, regex api_key/token/secret/password/auth/cookie/credential) | IMPLEMENTED | hermes_harness.py:228,354-359 |
| CFG-HERMES-003 | `model.default` = the main alias, `base_url` = main node; every AUX task uses the same alias | IMPLEMENTED | hermes_harness.py render |
| CFG-HERMES-004 | `compression.enabled: true` (threshold 0.75 etc., agent overrides) | IMPLEMENTED | hermes_harness.py render |
| CFG-HERMES-005 | `mcp_servers` = user entries (secrets stripped) overlaid by graph-declared `agents.<a>.mcp` with `${VAR}` refs | IMPLEMENTED (b3e282d) | hermes_harness.py mcp_servers |
| CFG-HERMES-006 | Lean profile: `platform_toolsets.cli` narrowed to LEAN_TOOLSETS + declared `mcp-*`; LEAN_AUX_DROP removed | IMPLEMENTED | hermes_harness.py lean_toolsets |
| CFG-HERMES-007 | Refuses to render into `~/.hermes` | IMPLEMENTED | hermes_harness.py render |
| CFG-HERMES-008 | Plugins/reaches are symlinked into HERMES_HOME only when declared | IMPLEMENTED | link_plugins / link_reaches |
