# Skills

A skill is a folder of instructions (a `SKILL.md`, sometimes with scripts) that
teaches an agent one job, such as probing a host, formatting a manuscript or
driving an Android device. A small local model running on old hardware leans on
these more than a large hosted one does, so familia lets you choose them from
a menu.

- **Home:** bundled skills live in **green-zkillz**, the `skills/` tree of
  `brianreborn/green-agentz`. `sh scripts/configure.sh` checks it out at the
  commit pinned in `pins.txt`.
- **Catalog:** `skills/catalog.json` lists every skill with its license,
  pinned commit and status. The format is in `skills/README.md`.
- **Selection:** turning a skill on writes `skills: [ids]` under the agent in
  `graph.yaml`. The comments in the file are kept, and the graph check
  validates the entry.
- **Licenses:** before a skill is turned on, `scripts/licenses.py` shows the
  licenses your new selection brings in and asks you to accept them (see
  `docs/licenses.md`).

```sh
./familia-menu.sh                                # Skills > Bundled skills
scripts/skills.py list                           # what exists, license, status
scripts/skills.py enable green-probe --dry-run   # see the change first
scripts/skills.py enable green-probe             # asks you to accept licenses, then saves
scripts/skills.py disable green-probe
scripts/skills.py vendor artemis-android-skill --dry-run   # plan only
```

## Rules

- A `license-blocked` skill can't be enabled. The message tells you why.
- An `available` skill can't be enabled until it is vendored into
  green-zkillz, because there are no files to load before that. Vendoring
  itself is still manual and waits on license review (familia #67).
- A pentest role never gets a skill with `adds_tools: true`. Both
  `skills.py` and the graph check refuse it.

## Status

Seeded with the seven green-zkillz skills (bundled, BSD-3-Clause) and the
familia #67 survey: `artemis-android-skill` (Apache-2.0, available) and the
GoClaw `skills/` set (license-blocked). hermes does not yet load the enabled
skills on its own; `scripts/skills.py paths` prints their folders, and the
tracking issue is [familia #72](https://github.com/brianreborn/familia/issues/72). The plan for vendoring
survey skills into green-zkillz is [green-agentz #17](https://github.com/brianreborn/green-agentz/issues/17).
