# Heavyweight-model escalation (semi-automatic)

The light node (e.g. `qodesh-smol-cpu`, SmolLM2) handles everything by default.
When a session looks stuck, familia can swap in a heavier model, then swap back.

> **Status (2026-10-19):** the graph fields, the decision/consent/handoff CLI and the
> hermes proxy (`scripts/hermes.sh --escalate`) are implemented and unit-tested
> against mock servers. The green-roomz router hookup, live swap, reachability
> probe, richer signals and a live end-to-end run are planned
> ([#39](https://github.com/brianreborn/familia/issues/39)).

## Graph fields (per node, optional)

```yaml
escalates_to: [coder, qodesh-resident]   # ordered fallback list; may be on other hosts
escalation:
  mode: suggest        # off | suggest (default) | auto
  triggers:            # all optional; defaults shown
    repeat_outputs: 3  # N (near-)identical consecutive outputs
    similarity: 0.9    # token-set Jaccard counted as near-identical
    failure_retries: 3 # failed tool calls / tests
    phrases: ["try harder", "escalate", "use the big model", "heavier model"]
    tags: ["hard", "multi-file"]
    time_budget_s: 600
```

Validation (`scripts/graph_types.py` -> `escalation.check_node_escalation`): targets
must exist, no self/duplicate targets, no cycles, known mode/trigger keys, and
suggest/auto need at least one target. Cross-host targets are allowed and are
reported as `crosses_host: true`.

## Decision (`scripts/escalation.py`)

`decide(graph, node, signals, registry_records, consent, reachable)` returns
`none`, `suggest` or `auto`:

- Signals: `outputs`, `failures`, `user_messages`, `tags`, `elapsed_s`, `reply_tokens`.
- Targets are ranked by best measured tg t/s from `registry/records.jsonl` for that
  model on that host (e.g. miryam `coder` 17.4 t/s beats `qodesh-resident` 0.91 t/s);
  unmeasured targets go last; unreachable hosts are dropped. ETA = reply_tokens / t/s.
- The system may suggest an edge but never opens one unasked. `auto` only applies
  when the node's mode is `auto` AND (same host OR consent recorded for that
  node -> target). Otherwise it is a `suggest` with a ready prompt for the user.
- Consent: `.cache/familia/escalation-consent.json`, written by
  `scripts/escalate.py consent --node X --target Y` after the user's first yes.

## Handoff and swap back

`handoff(turns, problem)` builds a compact payload (open problem + last 6 turns,
each clipped to 600 chars) so a slow heavy model does not spend minutes reading
the full history. The decision carries `swap_back_to`: route back to the light
node once the heavy reply lands.

## CLI

```
python scripts/escalate.py decide --node qodesh-smol-cpu --signals s.json [--reachable qodesh,miryam]
python scripts/escalate.py consent --node qodesh-smol-cpu --target coder
python scripts/escalate.py handoff --signals s.json
python scripts/escalate.py accept       # accept the pending suggestion from the proxy
```

## hermes integration (implemented, behind a flag)

`scripts/hermes.sh --escalate [--light NODE] [--no-swap-back] -- <hermes args>`
starts `scripts/escalation_proxy.py` on 127.0.0.1 (random port), renders the
hermes config to point at it, and runs hermes as a child.

Escalation belongs to hermes.sh's **graph mode**, the default. In graph mode the proxy also
comes on without `--escalate` when the agent's main node declares `escalates_to` and its
`escalation.mode` is not `off`. No node used by an agent declares it today, so the default
launch has not changed. `--no-escalate` turns the proxy off. **Single-model mode**
(`hermes.sh --model NODE`) has no router and no proxy: `--escalate`, `--light`,
`--no-swap-back` and `--no-escalate` exit with code 2 there. Self-improving harnesses
([harness2.md](harness2.md)) never change escalation settings. A descriptor has no field
for them.

- **Sessions / concurrency (#101):** the proxy is a `ThreadingHTTPServer`. Each
  session has its own `Escalator` (signals, current node, pending, handoff) behind
  an RLock. Send `X-Familia-Session: <id>` (preferred) or an `Authorization: Bearer`
  token so concurrent clients do not share state. Requests with neither header share
  the `default` session and are serialized by that session's lock — hermes does not
  send a session id today, so multi-session isolation needs the header.
- Signals come from the traffic: assistant replies (repeat detection), `tool`
  messages since the last user turn matching error/traceback/failed/exit code N,
  the last user message (phrases), elapsed time, upstream errors.
- `suggest`: prompt printed to stderr, appended to the reply hermes shows, and
  written to `.cache/familia/escalation-pending.json`. Accept with
  `python3 scripts/escalate.py accept` (applies on the next request; a first yes
  to a cross-host target records consent). `FAMILIA_ESCALATE=auto` accepts
  same-host suggestions automatically.
- `auto` (or accepted): local target started via `validate_graph.py` args
  (`ensure_server`), next request goes to the target alias with the compact
  handoff (tools kept, #106), then the proxy swaps back after one clean reply.

## Remaining / stubbed (planned, #39)

- Cross-host targets bound to 127.0.0.1 (all current nodes, e.g. miryam `coder`)
  are reported unreachable: an ssh tunnel (nexus) is not opened automatically.
- "Clean reply" = HTTP 200; no check that the heavy model actually solved it.
- Task tags are not collected from hermes; elapsed time resets only on swap back.
- Not yet run live against hermes-agent; tested with mock llama-servers only.
- green-roomz route node is not wired; the CLI/proxy is the integration surface.
