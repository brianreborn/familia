---
name: protograph
description: >-
  Configure a familia graph.yaml from a short recipe: pick host, runtime,
  models and nodes, emit a canonical typed graph (schema v2) with every
  value explicit, validate it (types, model database, launch parameters,
  RAM budget), show a dry run, and write only after confirmation. Use when
  someone asks to set up, extend, or rebuild a graph for a host, or to
  turn a plain-language "run X as a coder on Y" request into graph.yaml.
---

# Protograph: recipe -> graph.yaml

Agent/tool-agnostic skill (#399; design origin #327). It names no particular
agent, connector or model. Any agent that can read files and run a command
can follow it; a person can follow it by hand.

Where this skill and the code disagree, the code wins
(`scripts/protograph.py`, `scripts/validate_graph.py`, `docs/graph-types.md`).
Report the disagreement instead of working around it.

## Rules

1. **Host-only.** Work on the machine that will run the graph. Do not
   download models, runtimes or tools. If something is missing, say what and
   which menu item gets it (Models: Add a model / Download and add a model);
   the person runs it.
2. **Dry run first, always.** Show the emitted graph and the plan before any
   write. Never write `graph.yaml` (or any existing file) without an explicit
   yes from the person, given after they saw the dry run.
3. **Explicit values.** graph.yaml has no implicit defaults. Every default the
   recipe leaves out is written into the graph and listed in the plan.
4. **No secrets, no real addresses.** `hosts.*.addr` / `user` stay
   `REPLACE_ME`; real ones live in `hosts.local.yaml` (#104).
5. **Loopback only.** Nodes bind `127.0.0.1`. LAN exposure is a hand edit
   with its own review, never a recipe output.
6. **RAM safety.** Respect `ram_mib - reserve_ram_mib` (docs/ram-safety.md).
   An over-budget plan is an error, not a warning.
7. **Measured means measured.** Never mark a host or GPU `measured: true`
   unless you measured it (scripts/host_measure.py). Copy, do not invent.

## Procedure

1. **Gather.** Ask (or read from the request): which host, which roles
   (chat, coder, decision, embed, ...), which models, which agent. Prefer
   what graph.yaml already knows: `host: {from_graph: NAME}`,
   `runtime: {from_graph: NAME}`, `models: {KEY: {from_graph: KEY}}`.
   To choose a model for a host, use `scripts/model_pick.py list --host H
   --role R` when it is present (#398).
2. **Write the recipe** (YAML, anywhere outside graph.yaml):

   ```yaml
   protograph: 1
   host: {from_graph: box}                 # or name/kind/os/cpu/threads/ram_mib/reserve_ram_mib
   runtime: {from_graph: llama-b11374-box-cpu}   # or name/build/commit/supported_archs/backends
   models:
     draft: {from_graph: qwen35-08b-q4km}  # or gguf/sha256/arch/trained_ctx/role/db
   nodes:
     - {role: coder, model: draft, ctx: 8192, port: 9101,
        override_reasons: {ctx: "why this differs from the model card"}}
   gateway: {port: 8090}                   # optional, default 8080
   agent: {kind: hermes-agent, main: coder, min_ctx: 8192}   # optional
   ```

   Working samples: `skills/protograph/examples/*.recipe.yaml`.
3. **Dry run.** `python3 scripts/protograph.py RECIPE`. Read the plan lines
   (copied parts, defaults filled, RAM estimate) and every ERROR / WARNING.
4. **Fix and repeat** until `python3 scripts/protograph.py RECIPE --check`
   prints `protograph: OK`. Typical fixes: a ctx that differs from the model
   card needs `override_reasons.ctx`; an arch the runtime does not list needs
   a newer runtime pin (do not drop the model); a duplicate role needs `name`.
5. **Confirm, then write.** Show the person the dry run and the target path.
   After an explicit yes:
   `python3 scripts/protograph.py RECIPE --out PATH --write` (add `--yes`
   only when they confirmed overwriting an existing file). An overwritten
   file is kept as `PATH.bak-YYYYmmdd-HHMMSS`. Prefer `generated/` paths;
   graph.yaml is never force-written past validation errors.
6. **Hand off.** Tell the person the next commands, for example
   `python3 scripts/validate_graph.py --graph PATH --host H` on that host
   (file and RAM checks), then `sh scripts/serve.sh NODE`.

## Output format for a run report

- Recipe used (inline YAML).
- `graph_definition`: the emitted YAML, or the path written.
- Plan lines and validation result (OK / errors).
- `required_tools` / `installation_plan`: what is missing on the host and
  which menu item provides it. Nothing is installed by this skill.
- Any skill/code/doc inconsistency found.

## Menu

Advanced: models & graph -> "protograph: recipe -> graph.yaml (dry run)"
(`adv.protograph`, CLI `familia graph proto RECIPE`).
