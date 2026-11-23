# Command-line builder helper (living requirements)

Issue: https://github.com/brianreborn/familia/issues/69
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:27 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

```

**Issue #69: Command-line builder helper (living requirements)**

A helper that assembles small, valid sets of options for familia commands, so users don't have to remember flags. For example, it picks `hermes.sh --model coder` vs `hermes.sh --graph`, or `add-model.sh DIR --damp-run`.

**This is a living issue:** add requirements as comments or checklist lines here whenever they're discovered, and fold them into the list below.

## Requirements (so far)
- [ ] Builds commands from small option sets, for example the mode (single model / graph), model node, dry-run / damp-run, accept-licenses, and self_improve mode.
- [ ] Option choices are generated from real sources, never hardcoded: `graph.yaml` nodes and hosts, model database entries (`registry/models/`), the skills catalog, and each script's `--help`/argparse spec.
- [ ] Rejects invalid combinations the same way the scripts do, e.g. a model node under hermes's 64K context floor, `self_improve` on pentest nodes, or flags that don't apply in a mode.
- [ ] Shows the final command before running it (copy/paste friendly, so users learn the CLI). It can print only, or run on confirm. Supports `--dry-run`.
- [ ] Usable from the menu (familia-menu.sh, generated menus) and on its own, with a non-TTY fallback: print the options and exit 2 instead of hanging.
- [ ] Runs the license gate (`scripts/licenses.py check`) before running anything

-- swarm/box
