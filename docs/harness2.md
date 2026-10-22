# Self-improving harnesses (Harness²)

> **Status: experimental, off by default** ([#65](https://github.com/brianreborn/familia/issues/65)).
> Research follow-ups: RRSI regularization ([#66](https://github.com/brianreborn/familia/issues/66)),
> Terminal-RSI ([#68](https://github.com/brianreborn/familia/issues/68)). Both are design-only.

[Harness²](https://github.com/google-research/harness2) (Google Research, Apache-2.0) improves
an agent's *harness*: its system prompt, guardrails, memory and skills. It runs the agent on
some tasks, has an editor model propose changes, runs the changed harnesses, picks one, and
writes down what it learned. familia uses it as a **separate settings layer**:

- It can attach to **any** harness, whether that is hermes, a code-bootstraps agent, a green-roomz
  agent or a plain folder of prompt files with no agent at all.
- **hermes does not need it.** `scripts/hermes.sh` works the same when Harness² is absent or off.
- **It does not need hermes.** Proposing, accepting and reverting only read and write the
  target's files and call a local model endpoint.
- **You can combine them.** When the graph turns it on for an agent, `hermes.sh` puts the
  accepted harness version in place before it starts (see [Using it with hermes](#using-it-with-hermes)).

Neither side imports the other. The boundary is one *target descriptor* (prompt, guardrails,
memory and skills paths plus an endpoint), and hermes reaches Harness² only by running
`scripts/harness2.py sync` as a subprocess.

There is no Harness² launcher. `scripts/harness2.py` reviews changes and never starts an agent.

## Declaring it in graph.yaml

Two top-level types. Both are checked by `scripts/validate_graph.py`.

```yaml
harnesses:                       # target descriptors: which files, which endpoint
  hermes-lab:
    kind: files
    agent: hermes-lab            # optional; links it to an agent so hermes.sh can pick it up
    root: ~/.cache/familia/hermes-hermes-lab
    prompt: SOUL.md              # required
    # guardrails: GUARDRAILS.md  # optional; when omitted, a "## Guardrails" section of the prompt
    # memory: MEMORY.md          # optional; when omitted, a "## Long-term memory" section
    skills: skills               # optional; without it, proposals that add skills are rejected
    node: coder                  # local node used to edit and to evaluate (must bind loopback)

self_improve:                    # optimizer settings that point at descriptors
  harness2:
    experimental: true
    engine: harness2
    mode: "off"                  # "off" | propose | apply   (quote off: YAML reads bare off as false)
    targets: [hermes-lab]
    k: 1                         # candidates per stage (max 4)
    recursion: parallel          # parallel = Harness² agg, sequential = seq
    tasks: coding-v1             # registry/harness2-tasks/coding-v1.json
    max_tasks: 3                 # cap per split for one run
```

| mode | what happens |
|---|---|
| `off` | Nothing runs, and launchers sync nothing. `propose --enable` makes one manual run. |
| `propose` | `harness2.py propose` creates a proposal. You review it and accept it yourself. |
| `apply` | Like `propose`, but a proposal that passes the gate and doesn't score lower than the base on either split is accepted by itself. This needs `harness2.py consent --target T` once first. |

The repo's `graph.yaml` declares the `hermes-lab` agent (experiments only), its descriptor
and a `harness2` setting with mode `"off"`.

## Commands

```sh
scripts/harness2.py status                                   # every target: setting, version, endpoint, engine
scripts/harness2.py set --agent hermes-lab --mode propose    # switch one agent (graph.yaml, comments kept); --dry-run shows the edit
scripts/harness2.py review                                   # pending proposals; on a terminal: accept / skip / revert
scripts/harness2.py install                                  # fetch the pinned engine (below)
scripts/harness2.py propose --target hermes-lab --dry-run    # plan and call estimate; no model calls
scripts/harness2.py propose --target hermes-lab [--enable] [--max-tasks N] [--k K] [--start-node] [--record]
scripts/harness2.py list   --target hermes-lab
scripts/harness2.py show   --target hermes-lab ID            # diff, scores, Harness²'s reason and lesson
scripts/harness2.py accept --target hermes-lab ID            # writes the target's files (new version)
scripts/harness2.py revert --target hermes-lab [--to 0000]   # parent version; 0000 restores the original files
scripts/harness2.py consent --target hermes-lab [--revoke]   # for mode apply
scripts/harness2.py sync   --target hermes-lab [--into DIR]  # write the current version (what launchers call)
scripts/hermes.sh harness2 status                            # same CLI, through hermes.sh
```

`--root DIR` swaps in a scratch copy of the target's root. `--state DIR` (or
`FAMILIA_HARNESS2_STATE`) moves the state directory, which defaults to `.cache/familia/harness2/`.

`set` edits only the `mode:` or `targets:` line it needs. If the agent has no descriptor and
is a `hermes-agent`, `set` declares one using the HERMES_HOME layout. If the agent shares a
setting with other targets, `set` gives it its own `self_improve.harness2-<target>` entry. The
edited graph is validated before it is written, so a pentest agent is refused. Turning a mode
on runs the license review first (`scripts/licenses.py gate`; `--yes` accepts). Harness² is
Apache-2.0 and shows up in the review once it is on. `apply` also needs
`scripts/licenses.py check` to pass before it accepts anything by itself. The menu group
**Self-improving harness (Harness2)** runs `status`, `set` and `review`.

`propose` needs the node to be running. Start it with `sh scripts/serve.sh coder`, or pass
`--start-node`: the license gate runs, then the node is started from `validate_graph.py --args` and stopped when the run ends.

## What one `propose` does

1. On first use it records version `0000`, which is the target's own files as they are
   (or `harness/base/` where a file doesn't exist yet). It also backs up the originals.
2. It runs Harness²'s `run_domain` over the **evolve** tasks of the task set. familia's
   adapter replaces Harness²'s OpenCode/Vertex sessions with one chat call to the local node.
   The context files are inlined in the prompt, and the reply's
   `<file path="harness/...">...</file>` blocks become the edits. No bun, no OpenCode, no
   cloud credentials. The executor is the target model answering the task under the
   candidate harness. It sees only a self-check ("compiles, defines the function"), never the
   hidden asserts.
3. The tree Harness² chose for the last task goes through familia's **gate**, described below.
4. Base and proposal are both run on the evolve and **holdout** tasks. Each answer is scored by
   that task's asserts, in a throwaway subprocess with CPU and memory limits. The editor never
   sees the holdout tasks.
5. The proposal is saved with its diff, scores, call count, tokens and wall time:
   `pending` (passed the gate), `rejected` (failed it) or `no_change` (Harness² kept the base).
   `--record` appends the measurement to `registry/records.jsonl`.

`accept` re-checks the gate. It refuses a proposal made against a version other than the
current one, writes the files, and makes a new version. `revert` steps back to the parent
version. `0000` restores the original files exactly and removes the skill folders Harness²
created.

## Safety

These rules are fixed, not settings.

- **Pentest agents are excluded.** A `self_improve` entry that is not `"off"` fails validation
  if a target's `agent` is used by any `pentests.*` entry. The model role does not restrict
  improvement; all model types can be used when an improvement subsystem is engaged. A
  `self_improve` entry that is `"off"` is inert, so declaring one never trips a check.
- **Files only.** A descriptor has fields only for prompt, guardrails, memory and skills.
  Validation rejects unknown fields such as `tools`. Harness²'s tool descriptions are shown to
  the editor but frozen. Scripts, plugins and sub-agents in a proposal reject the whole
  proposal.
- **No tool or permission widening.** Added lines that enable or unlock tools, the shell,
  network or exec, that ignore or bypass guardrails, safety or approvals, or that contain
  `sudo`, `curl`/`wget`/`ssh`/`nc` commands, `rm -rf`, `disabled_toolsets` or `approvals: off`
  are rejected. The check errs on the side of rejecting.
- **No leakage.** Added text that names a task id or a task's function name is rejected, so
  the harness stays task-agnostic.
- **Local only.** The node must bind 127.0.0.1, localhost or ::1, and the CLI refuses any other
  endpoint.
- **Your skills are safe.** Export never overwrites a skill folder it didn't create. Skills
  enabled through `scripts/skills.py` ([docs/skills.md](skills.md)) and hand-made ones stay as
  they are.
- **The engine is pinned.** `install` downloads
  `google-research/harness2@1cfe254e8d25` as a tarball, checks its sha256
  (`2337f91b…748f`), and unpacks only the `harness2/` package, `LICENSE` and `pyproject.toml`
  (about 0.6 MB) into the state directory. Nothing is pip-installed. Upstream asks for Python
  3.12 or 3.13. The core library ran on miryam's Python 3.14.4.

## Using it with hermes

`hermes.sh` picks Harness² up only when the graph has a `harnesses.<T>` with
`agent: <the agent being launched>` and a `self_improve` entry with mode not `"off"` that targets
it. `--self-improve` forces the pickup for one launch even while the mode is `"off"`. The
pickup runs `scripts/harness2.py sync --target T` before hermes starts.

- **Graph mode** (`hermes.sh --agent hermes-lab`): the descriptor root *is* that agent's
  HERMES_HOME, so `accept` and `revert` already wrote `SOUL.md` and `skills/`. The sync is a
  consistency check.
- **Single-model mode** (`hermes.sh --agent hermes-lab --model coder`): HERMES_HOME is
  `~/.cache/familia/hermes-hermes-lab@coder`, and the sync writes the current version there
  (`--into`).
- If `scripts/harness2.py` is missing, hermes starts anyway and prints a note. If a sync fails,
  it prints the error and starts with the files as they are.

hermes injects `SOUL.md` as its system prompt. Guardrails and memory become sections of it,
because hermes has no separate files for them. To run hermes without accepted changes, revert
(`harness2.py revert --target hermes-lab --to 0000`).

## Without hermes

Point a descriptor at any folder and leave `agent` out:

```yaml
harnesses:
  bootstraps-prompts:
    kind: files
    root: ~/src/my-agent
    prompt: prompts/system.md
    guardrails: prompts/guardrails.md
    node: coder
```

Then `propose`, `show`, `accept` and `revert` work on those files. The agent that reads them is
up to you.

## Cost

Calls for one `propose`, roughly: `n_evolve × (2k + 3)` for Harness², plus
`2 × (n_evolve + n_holdout)` for the evaluation. `--dry-run` prints the estimate. Editor
prompts are 11 to 14 K characters, plus the inlined files (capped at 90 K characters), which
fits the 64 K window on `coder`.

On miryam (Qwen3.5-2B Q4_K_M, CPU, two threads), one run with `--max-tasks 1`
and `k=1` (2026-10-19, other jobs sharing the CPU) took **58 minutes**: 12 model calls and 4,890
completion tokens. Prompt processing ran at about 14 to 17 tokens per second and generation at
about 3.5 to 4.4, so each editor call (about 4,600 prompt tokens) took around 8 to 10 minutes.
The measurement is in `registry/records.jsonl` (`kind: harness2`). It is a coarse binary search
(one pass, one rollout per task), not a benchmark.

What happened: the loop ran end to end, but Qwen3.5-2B did not follow the editor protocol. It
echoed the files instead of emitting `<file>` blocks, so no harness file changed. Base and
candidate both scored 0/1 on evolve and 0/1 on holdout. That run reported `pending` with an
empty diff. `propose` now reports `no_change` for a candidate whose editable files equal the
base. A useful editor needs a stronger local model than the 2B `coder` node, for example a
heavier node on another host. The executor can stay small.

## Limits

- The task set is small and synthetic: twelve Python function tasks, six evolve and six
  holdout. It shows whether the loop works, not whether a harness got better in general.
- A proposal carries the harness Harness² chose for the **last** evolve task. Lessons from
  earlier tasks reach it only through Harness²'s library within that run.
- Harness²'s own judge and reporting (`harness2.core.judge`) are not used. familia scores with
  its own asserts.
- RRSI-style regularization (#66): cost-aware acceptance, a noise-adjusted floor, a leakage
  critic beyond the term match. Terminal-RSI policy refinement (#68). Both are design-only.

## See also

- [Harness slimming](harness-slimming.md) (#89)
- [Official Hermes plugins](hermes-plugins.md) (#92)
