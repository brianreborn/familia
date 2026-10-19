# skills/: the familia skills catalog

`catalog.json` is the selection layer over **green-zkillz**, the home for
bundled skills (the `skills/` tree of
[brianreborn/green-agentz](https://github.com/brianreborn/green-agentz), pinned
in `pins.txt`). familia does not keep its own copy of skill files. Use
`scripts/skills.py` to work with it (see `docs/skills.md`). JSON is used so
that old devices without PyYAML can still read it.

## Entry format

| field | meaning |
|---|---|
| `id` | lowercase slug, used in `graph.yaml` `skills: [...]` |
| `name`, `description` | plain-language label and one line on what it does |
| `home` | `green-zkillz` (must be a key in `homes`) |
| `repo`, `commit` | source repo URL and the full 40-char SHA it is pinned to |
| `license`, `license_file`, `attribution` | license as stated by the source, path of its text, credit line to keep |
| `path` | skill folder inside the source repo |
| `applies_to` | agents it can be enabled for (e.g. `["hermes"]`) |
| `adds_tools` | `true` if it ships scripts, MCP servers or tool definitions; pentest roles never get these |
| `status` | `bundled` (in green-zkillz now), `available` (reviewed source, not vendored), `vendored`, or `license-blocked` |
| optional | `notes`, `vendor_plan`, `survey`, `blocked_reason` (required when blocked), `parts` (per-skill licenses of a set) |

`scripts/skills.py validate` checks this format, and `tests/test_skills.py`
covers it.

Move plan (vendoring survey skills into green-zkillz): https://github.com/brianreborn/green-agentz/issues/17.
hermes loading enabled skills: https://github.com/brianreborn/familia/issues/72.
