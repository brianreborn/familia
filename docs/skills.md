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
  green-zkillz, because there are no files to load before that. Artemis is
  now `vendored` (green-agentz #18); GoClaw remains license-blocked (#67).
- etioz is listed as `bundled` even though its own status is still
  awaiting-ratification. It adds no tools.
- A pentest role never gets a skill with `adds_tools: true` in its own
  `pentests.<name>.skills`. Skills inherited from the pentest's agent are not
  checked yet; that decision is deferred (#77). Both
  `skills.py` and the graph check refuse it.

## Status

Seeded with the seven green-zkillz skills (bundled, BSD-3-Clause) and the
familia #67 survey: `artemis-android-skill` (Apache-2.0, **vendored** into
green-zkillz via [green-agentz #18](https://github.com/brianreborn/green-agentz/pull/18))
and the GoClaw `skills/` set (license-blocked; not vendored). hermes loads
enabled skills via `scripts/hermes_modes.py` (`link_skills` → `skills.py paths`);
[familia #72](https://github.com/brianreborn/familia/issues/72) is closed.
Further survey vendors: [green-agentz #17](https://github.com/brianreborn/green-agentz/issues/17).
