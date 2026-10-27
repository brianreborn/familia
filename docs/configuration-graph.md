# The configuration graph

> **Status (2026-10-19):** implemented on `main` as typed, multi-host schema v2: [`graph.yaml`](../graph.yaml), [`scripts/graph_types.py`](../scripts/graph_types.py) and [`scripts/validate_graph.py`](../scripts/validate_graph.py). Every section and field is documented in [graph-types.md](graph-types.md); this page explains why the graph exists and what is still open. Items marked **TBD** are undecided. `illustrative` blocks show intent, not a supported syntax.

## Implemented today

`graph.yaml` declares `hosts` (measured RAM, CPU, GPUs, `reserve_ram_mib`), `runtimes` (llama.cpp builds side by side, with the architectures each was load-tested on), `models` (GGUF, sha256, arch, trained context, model-database entry), `nodes` (model servers: host, runtime, context, slots, KV type, offload, port, prompt cache, `selection: default|fallback`, card sampling, `escalates_to`), plus `aliases`, `agents`, optional `pentests` (none by default), `meshes`, `speculative` and `options` (catalog-only models).

```sh
python3 scripts/validate_graph.py                 # exit 0 if valid, else one line per problem
python3 scripts/validate_graph.py --graph FILE    # validate another file
python3 scripts/validate_graph.py --args coder    # print the llama-server command line for a node
```

What the validator checks now (full list in [graph-types.md](graph-types.md#rules-the-validator-enforces)):

- each runtime is installed on the node's host, and with `--check-runtimes` its binary reports the declared build;
- each node's GGUF `arch` is in its runtime's `supported_archs` (e.g. embeddinggemma-2 fails on b11374);
- an agent's `context_length` equals its node's per-slot context (`ctx / parallel`) and is at least `min_ctx` (the #19 case);
- `cache_ram_mib` is large enough to hold one slot's prompt state;
- each model has a model-database entry pinned to a revision, and a node's context and sampling match the model card unless `override_reasons` explains why ([model-database.md](model-database.md), #51);
- **RAM:** estimated use (weights + KV + 256 MiB overhead + `cache_ram_mib`) above `ram_mib` fails. Estimated use plus `reserve_ram_mib` above `ram_mib`, or less than 2 GiB free on a host under 8 GiB, is a warning. See [ram-safety.md](ram-safety.md).

Consumers: [`scripts/serve.sh`](../scripts/serve.sh) and [`scripts/hermes.sh`](../scripts/hermes.sh) launch `llama-server` from `--args`, and hermes.sh refuses to start hermes-agent unless the graph validates. `start.sh` does **not** read the graph yet.

## Why

Before the graph, a familia install configured itself mostly by inference (and `start.sh`, which doesn't read the graph yet, still does):

- the model server picks a RAM profile (`PROFILE=auto` → `lowram` / `moderate` / `default`) from free memory and CPU speed,
- a specialist route appears when a model file appears on disk,
- per-role context sizes come from that profile unless you override `CTX` / `CODER_CTX` / `GENERAL_CTX`,
- an agent (for example hermes-agent) is configured on its own, and nothing checks that its context budget fits the server's slot.

That is convenient, but when it is wrong you only see it later. The clearest case is [#19](https://github.com/brianreborn/familia/issues/19). hermes-agent sent 17,969 to 21,070-token requests to a `coder` slot of 16,384 tokens, with its compaction turned off. Every request failed with HTTP 400, and nothing in the setup noticed the mismatch before it happened.

The configuration graph turns this around. **You declare which models and agents exist and how they connect. familia measures the hardware, checks the declaration against those measurements, and either runs exactly what you declared or refuses with a clear error.**

## Principles

Items 1–6 are the stated goals of the effort. Item 7 is an existing DESIGN.md rule carried over.

These follow from rules already in [DESIGN.md](../DESIGN.md) ("The user is in control of every edge. The system fills only the hooks the user left open." and "Autoconfig may suggest one and must not open it.").

1. **Explicit.** Every model node names its route, its weights (by pinned identity), its engine, and its context. Every agent node names the routes it calls.
2. **Never a silent choice.** familia does not swap in a different model, quantization, or engine because the declared one doesn't fit. It may *suggest* one in the error message.
3. **Never silent context inflation.** Context sizes, slot counts, and resident models are what the graph says. familia doesn't raise context because there happens to be spare RAM. If the declaration doesn't fit the measured memory, validation fails. *(Proposed, not yet decided: the same rule in the other direction, so that familia never silently shrinks context to make a graph fit.)*
4. **Fail loudly on mismatch.** A failed check stops the start (or the reload) and names the node, the property, the declared value, and the measured value. Starting a graph that doesn't fit is not a warning-level event.
5. **Dynamic, but declared.** The graph can change at runtime: a machine joins, a model is added, an edge is turned on. Each change is a new declaration that is validated before it takes effect. "Dynamic" means re-validated on change. It does not mean re-guessed on start.
6. **Measured, not assumed.** Validation uses measured facts about the host (memory, accelerator presence, engine binaries actually present, weights actually present and hash-verified). Benchmarks are cached by host fingerprint, as DESIGN.md already specifies for green-roomz. A new fingerprint triggers requalification.
7. **Environment still wins, visibly.** An explicit environment variable or CLI flag still overrides the graph, as it does today. The override is part of what gets validated, and it is reported at startup.

## Concepts

### Nodes and hooks

The graph uses the node and transport names already reserved in [`pins.txt`](../pins.txt):

| Node | In the configuration graph | Hooks (from DESIGN.md) |
|---|---|---|
| `model` | One route name (`chat`, `coder`, `route`, `translate`, specialists) bound to declared weights and an engine | `in`, `weights`, `kv` |
| `agent` | An agent process: the code-bootstraps-llama.cpp agent, a green-agentz profile, or an external agent such as hermes-agent | `task`, `tools`, `local`, `remote` |
| `room` | A green-roomz alias in front of one backend | `in`, `handoff` |
| `swarm` | A green-fleetz member | `task`, `result` |
| `store` | Where weights or snapshots come from | `read`, `write` |
| `reach` | Agent-Reach tools | `query`, `result` |
| `agency` | Retired green-agency runs (kept for compatibility only) | `in`, `out`, `snap` |

Transports (`local`, `ssh`, `nfs`, `rsync`, `bittorrent`, `zfs`) label how an edge between machines moves bytes. Only the SSH nexus and private BitTorrent tracker have code, as an opt-in proof of concept ([transport-poc.md](transport-poc.md)); the rest are names only.

A hook that isn't connected is closed.

### Hosts

Each node is placed on a named host, meaning one of your machines. A host's facts (`ram_mib` is its measured MemTotal) are recorded in the graph, so validation is correct even when run elsewhere. The installers measure the host they run on and write its `hosts.<name>` block. **TBD:** how a remote host's measurements are gathered automatically.

### What a model node declares

Implemented (field names in [graph-types.md](graph-types.md)): route name (through `aliases`), weights identity (GGUF, sha256 and the pinned model-database entry), runtime, context and slot count, KV type, offload, host, port, prompt cache, and whether it is the default or a user-selectable fallback (`selection`). **TBD:** residency (always loaded or on demand), and a single engine spelling for forks (`ENGINE_CHAT=nace-ai__edlm` and `engine = llama-server__nace-ai__edlm` both appear in the docs).

### What an agent node declares

The aliases it calls (`main`, `auxiliary`), its `min_ctx` and its `context_length`. For hermes-agent, `scripts/hermes.sh` writes the compression settings into its own rendered config (compression on); familia never edits `~/.hermes`. **TBD:** how other external agents report and receive their context budget.

## Validation

Validation runs before start and before any change is applied. These are the checks planned so far. The list is not exhaustive and the order is TBD:

| Check | Status | Fails when |
|---|---|---|
| Weights present and verified | **Implemented** (hash with `--verify-sha`) | The declared weights are missing, or the hash doesn't match |
| Engine present | **Implemented** | The runtime isn't installed on the host; with `--check-runtimes`, the binary reports a different build. No fallback to another `llama-server` |
| Memory fit | **Implemented** | Estimated use exceeds `ram_mib` (error); reserve or small-host floor broken (warning) |
| Accelerator fit | **Implemented** | A node offloads layers to a GPU that isn't measured, verified, or big enough |
| Agent ↔ model context | **Implemented** | `context_length` differs from the per-slot ctx or is below `min_ctx` (#19) |
| Model card | **Implemented** (#51) | No pinned model-database entry, or ctx/sampling differ from the card without a reason |
| Alias uniqueness | **Implemented** | An alias resolves to more than one node, or crosses hosts without a transport |
| Specialist routes | Graph side only | Under the graph a weights file on disk does nothing until declared. `start.sh` still activates a specialist route when its file appears |

### Error shape (intent)

The intended shape of an error, not its literal wording:

```illustrative
familia: graph check failed (start refused)
  node      model coder @ <host>
  property  context per slot
  declared  32768
  measured  fits at most <N> with 2 slots (available <X> GiB)
  options   lower coder context in the graph, reduce slots, or move coder to another host
  familia did not change anything.
```

and for an agent:

```illustrative
familia: graph check failed
  edge      agent hermes → model coder
  agent     max request ~21000 tokens, compaction off
  model     16384 tokens per slot
  options   enable compaction in the agent, raise coder context (memory permitting), or cap the agent
```

## Relationship to today's settings

| Today | Under the graph |
|---|---|
| `PROFILE=auto` picks a profile from RAM | **TBD:** profiles may stay as named presets you can *declare*, but they are not chosen for you. |
| `PROFILE=lowram\|moderate\|default` | A declared preset is checked against measured memory. A failure is an error. |
| `CTX`, `CODER_CTX`, `GENERAL_CTX`, `PARALLEL`, `MODELS_MAX` | Become properties of model nodes. The environment variables still override, and the override is validated and reported. **TBD:** deprecation timeline. |
| `ENGINE_<ROUTE>` | Becomes the engine property of that route's model node. |
| Specialist auto-activation on file presence | Replaced by declaration plus presence. |
| `--pick`, `--step-up` (model fetch helpers in code-bootstraps-llama.cpp) | Remain download helpers. Downloading a file doesn't change the graph. **TBD:** whether a future host-management UI offers "add to graph" after a download. |

## Editing the graph

Edit `graph.yaml` by hand, or use `scripts/generate_graph.py HOST` / `scripts/modify_graph.py` for scripted per-host changes, then validate. A visual editor and natural-language configuration are future ideas, not planned yet; if they come, they must produce a declaration that goes through the same validation.

## Open questions

- How multi-host measurements are collected and trusted (ssh probe? an agent on each host?).
- Refining the memory estimator (today: weights + KV + 256 MiB + cache). The safety margin is decided: see ram-safety.md.
- Whether validation reruns on a schedule, only on change, or on every start (it reruns at least on every start and every change).
- How external agents other than hermes-agent report their context budget.
- Migration: how an existing launcher `panel.env` becomes a first graph without silently baking in today's auto-picked values. (Proposal: generate a draft declaration, show it, and require the user to accept it.)

## See also

- [DESIGN.md](../DESIGN.md): the graph, hooks, and the "user owns every edge" rule
- [pins.txt](../pins.txt): reserved node and transport names
- [ram-safety.md](ram-safety.md): the reserve rule
- [#19](https://github.com/brianreborn/familia/issues/19): the hermes context overflow that motivates the agent ↔ model check
