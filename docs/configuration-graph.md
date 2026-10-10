# The configuration graph

> **Status:** a first version is implemented on `fix/config-graph`: [`graph.yaml`](../graph.yaml) (schema v1, single host) and [`scripts/validate_graph.py`](../scripts/validate_graph.py). A typed, multi-host schema v2 exists only on the unmerged [`feat/graph-types`](https://github.com/brianreborn/familia/tree/feat/graph-types) branch. Sections below marked **TBD** are still design. `illustrative` blocks show intent, not a supported syntax.

## Implemented today (fix/config-graph)

`graph.yaml` has four top-level keys:

| Key | Meaning |
|---|---|
| `version: 1` | Schema version |
| `host` | Measured `ram_mib` (miryam: 7270) and `reserve_ram_mib` (miryam: **3072**) |
| `runtimes` | llama.cpp builds deployed side by side: `bin`, `tag`, `commit`, and `archs` (architectures load-tested on that build). Today `b11374` (qwen35) and `b11539` (gemma-embedding2) |
| `nodes` | Model servers: `runtime`, `model`, `arch`, `ctx`, `parallel`, `kv_type`, `flash_attn`, `gpu_layers`, `host`, `port`, `aliases`, `cache_ram_mib`, optional `embeddings`. Today `coder` (Qwen3.5-2B, 65,536 ctx, port 9941) and `embed` (embeddinggemma-2, port 9951) |
| `agents` | Agents and their requirements, e.g. `hermes` with `min_ctx: 64000` and `context_length: 65536` |

```sh
python3 scripts/validate_graph.py                 # exit 0 if valid, else one line per problem
python3 scripts/validate_graph.py --graph FILE    # validate another file
python3 scripts/validate_graph.py --args coder    # print the llama-server command line for a node
```

What the validator checks now:

- each runtime binary exists, is executable, and reports the declared version;
- each node's GGUF `arch` is in its runtime's `archs` (e.g. embeddinggemma-2 fails on b11374);
- an agent's `context_length` equals its node's per-slot context (`ctx / parallel`) and is at least `min_ctx` (the #19 case);
- `cache_ram_mib` is large enough to hold one slot's prompt state;
- **RAM:** estimated use (weights + KV + 256 MiB overhead + `cache_ram_mib`) plus `reserve_ram_mib` must fit `ram_mib`, and hosts under 8 GiB must keep about 2 GiB free after the estimate. See [ram-safety.md](ram-safety.md).

Consumers: [`scripts/hermes.sh`](../scripts/hermes.sh) refuses to start hermes-agent unless the graph validates, then renders hermes's config from it. `start.sh` and the settings panel do **not** read the graph yet.

On unmerged branches (not shipped): schema v2 with multiple hosts, GPU fields, speculative-decoding edges and a launch-test-only `pentests` type (`feat/graph-types`); `hosts`/`transports` with ssh and bittorrent (`feat/transport-poc`); `derived_from` checks for scaled-down models (`feat/scale-down`).

## Why

Before the graph, a familia install configured itself mostly by inference (and `start.sh` still does):

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

Transports (`local`, `ssh`, `nfs`, `rsync`, `bittorrent`, `zfs`) label how an edge between machines moves bytes. In the current revision they are names only, with no protocol code.

A hook that isn't connected is closed.

### Hosts

Each node is placed on a host, meaning one of your machines. Schema v1 describes one host (`host.ram_mib` is that host's measured MemTotal, so validation is correct even when run elsewhere). Named multi-host placement is on `feat/graph-types` (unmerged). **TBD:** how a remote host's measurements are gathered automatically.

### What a model node declares

Decided in principle (the field names are TBD):

- route name
- weights identity: file plus pinned source and hash, matching what `config/models-manifest.json` already pins in code-bootstraps-llama.cpp
- engine identifier (`llama-server`, or `<executable>__<author>__<branch>` for an alternative build). **TBD:** a single spelling. Today `ENGINE_CHAT=nace-ai__edlm` and `engine = llama-server__nace-ai__edlm` both appear in the docs.
- context per slot and slot count
- residency (always loaded, or loaded on demand)
- host

### What an agent node declares

- which routes it calls (edges to `model` or `room` nodes)
- the largest request it may send (its context budget)
- whether it compacts or compresses, and at what threshold. **TBD:** how familia reads or sets this for external agents. For hermes-agent, the relevant settings live in `~/.hermes/config.yaml` (`compression.enabled`, `compression.threshold`).

## Validation

Validation runs before start and before any change is applied. These are the checks planned so far. The list is not exhaustive and the order is TBD:

| Check | Fails when |
|---|---|
| Weights present and verified | The declared weights are missing, or the hash doesn't match the pin |
| Engine present | **Implemented** for `runtimes:`. The declared binary is missing or reports a different version. (No fallback to another `llama-server`.) |
| Memory fit | **Implemented.** Estimated use plus `reserve_ram_mib` exceeds `ram_mib`, or a host under 8 GiB would keep less than ~2 GiB free |
| Accelerator fit | A node declares GPU offload and no usable device is measured. (The sub-project already warns that a CPU-only binary with a GPU present is a mismatch. This makes it an error in the graph.) |
| Agent ↔ model context | **Implemented** (as exact `context_length` = per-slot ctx ≥ `min_ctx`; hermes.sh turns compaction on). This is the #19 case. |
| Route uniqueness | Two nodes publish the same route name |
| Edges | An edge connects a hook that doesn't exist, or crosses hosts without a declared transport |
| Specialist routes | A specialist route has a weights file on disk but no declaration. Today this activates the route. Under the graph it only produces a notice and the route stays off. |

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
| `--pick`, `--step-up` (model fetch helpers in code-bootstraps-llama.cpp) | Remain download helpers. Downloading a file doesn't change the graph. **TBD:** whether the panel offers "add to graph" after a download. |

## Editing the graph

DESIGN.md requires two ways to configure: a visual, netgraph-style editor for anything from one host to a federated multi-host setup, and a natural-language description. Under this design, both produce a declaration that goes through the **same validation**. Neither may bypass it. **TBD:** the editor, the declaration file format, and where it is stored (likely under the familia tree or `.cache/`, which is undecided).

## Open questions

- Declaration format: `graph.yaml` at the repo root (v1). Whether v2 replaces it is decided when `feat/graph-types` merges.
- How multi-host measurements are collected and trusted (ssh probe? an agent on each host?).
- Refining the memory estimator (today: weights + KV + 256 MiB + cache). The safety margin is decided: see ram-safety.md.
- Whether validation reruns on a schedule, only on change, or on every start (it reruns at least on every start and every change).
- How external agents (hermes-agent and others) report their context budget, and whether familia may write their config or only check it.
- Migration: how an existing `panel.env` becomes a first graph without silently baking in today's auto-picked values. (Proposal: generate a draft declaration, show it, and require the user to accept it.)

## See also

- [DESIGN.md](../DESIGN.md): the graph, hooks, and the "user owns every edge" rule
- [pins.txt](../pins.txt): reserved node and transport names
- [ram-safety.md](ram-safety.md): the reserve rule
- [#19](https://github.com/brianreborn/familia/issues/19): the hermes context overflow that motivates the agent ↔ model check
