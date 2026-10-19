# Licenses: what you agree to before anything runs

familia pulls together models, skills, engines and other repos, and each has
its own license. Some of these are not standard open source. Before familia
installs, fetches or starts anything, `scripts/licenses.py` lists every license
your current selection brings in and asks you to accept them.

```sh
scripts/licenses.py review        # show the list and accept it (asks on the terminal)
scripts/licenses.py check         # exit 0 if this selection is already accepted
scripts/licenses.py list --json   # machine-readable list; records nothing
```

## What it covers

- **Models** used by `graph.yaml` nodes. The license comes from the model
  database entry (`registry/models/*.json`), with the full text in the
  fetched Hugging Face snapshot (`hf-meta/<repo>/<revision>/LICENSE`, or the
  model card when the repo has no LICENSE file). The code-bootstraps manifest
  `notice` is shown when it has one.
- **Skills** you enabled (`skills:` under an agent; see `docs/skills.md`).
- **Engines**: llama.cpp builds used by nodes (MIT), hermes-agent (MIT), and
  Harness2 (Apache-2.0) only when it is switched on.
- **Components**: familia itself and every repo in `pins.txt`, read from its
  LICENSE file. A repo with no LICENSE file is marked **unknown**, unless
  `scripts/licenses.py` has a declared license for it. green-roomz and
  green-agentz got their LICENSE files (the Light-ware License) after the
  revisions pinned in `pins.txt`, so their declared license is used (#75).

Items are grouped by license. These come first:

- **unknown**: no license found. These block until you accept them on purpose
  (type `accept unknown`, or pass `--accept-unknown`).
- **restrictive**: non-commercial, acceptable-use policy, region limits, gated,
  or proprietary.
- **custom**: not OSI-approved (for example LFM `lfm1.0`, Tencent HY
  Community License, Gemma terms, and familia's own Light-ware License, which
  has a BSD-4 advertising clause).

familia's own license, and green-roomz and green-agentz, which use the same
text, show up under **custom / needs attention** on purpose. The advertising
clause (condition 3) is a real obligation that OSI-approved licenses don't
have, so you should see it before you accept. This is deliberate, not a bug.

For each one it shows what it is used for, where the full text is on disk, a
link, and lines quoted from the license or card that carry obligations. These
are quoted lines, not legal advice. Read the full text.

## When you are asked

Your acceptance goes in `.cache/familia/license-acceptance.json`, together
with a hash of the selection and its licenses. You are asked again only when
that hash changes, for example when you add a model, enable a skill, or a pin
moves.

The gate runs before `familia-menu.sh` install, start and fetch actions, in
`install.sh`, `start.sh` and `with-fleet.sh`, in the Windows entry points, and
when you enable a skill.

## Non-interactive use

`--yes` (or `--accept-licenses`, or `FAMILIA_ACCEPT_LICENSES=yes`) accepts
without a prompt, but the summary is still printed. Unknown licenses also need
`--accept-unknown` (or `FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes`). If there's no
terminal and no `--yes`, the gate prints the list and exits 2 rather than
waiting for input.

Exit codes: 0 accepted, 1 not accepted yet or changed, 2 usage or no terminal,
3 unknown licenses not accepted. Other scripts should call
`scripts/licenses.py check` (or `gate` to prompt), and that CLI stays stable.
