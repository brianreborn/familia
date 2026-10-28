# Hermes frontend clients (CLI, Desktop, Webapp)

Familia treats these as **equal-tier frontend clients** against graph-backed
models. None of them is the backend; none is a flagship product track.

| Client | How familia launches it | Upstream surface |
|---|---|---|
| **CLI** (default) | `scripts/hermes.sh` → `hermes` / `hermes-agent` chat | Terminal CLI / TUI |
| **Desktop** | `scripts/hermes.sh --client desktop` → `hermes desktop` | Native Electron app (`apps/desktop/`) |
| **Webapp** | `scripts/hermes.sh --client webapp` → `hermes webapp` | Same Desktop renderer in a browser via the gateway |

Docs upstream: [Hermes Desktop](https://hermes-agent.nousresearch.com/docs/user-guide/desktop).

## familia wiring

`scripts/hermes.sh` still owns validate → licenses → render `HERMES_HOME` →
ensure llama-server → warm_prompt. Only the **final exec** changes with
`--client`:

```sh
scripts/hermes.sh --model coder --yes                    # CLI (default)
scripts/hermes.sh --model coder --client desktop --yes   # native Desktop
scripts/hermes.sh --model coder --client webapp --yes    # desktop-as-webapp
```

- `--client webapp` sets `webapp.enabled: true` in the rendered HERMES_HOME
  `config.yaml` (idempotent) before exec.
- Extra hermes flags still go after `--` (for example
  `… --client desktop -- --cwd /path/to/project`).
- If the resolved binary has no `desktop` / `webapp` subcommand, the launch
  refuses with an actionable message (probe skipped when
  `FAMILIA_HERMES_CLIENT_PROBE=0`).

Backend concerns (llama-server, graph nodes, angel warm, swap) stay on the
server side. Desktop and webapp talk to Hermes the same way the CLI does once
`HERMES_HOME` points at the familia-rendered profile.

## familia AppImage ≠ Hermes Desktop

| Artifact | What it is |
|---|---|
| **familia** AppImage (`packaging/appimage/`, `docs/appimage.md`) | Single-file entry for **familia** (menu / CLI / settings). Not Hermes Desktop. |
| **Hermes Desktop** installers | Upstream Electron app from [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) / the [Hermes Desktop product page](https://hermes-agent.nousresearch.com/). |

Do not vendor Electron into familia. Prefer:

1. Install Hermes per upstream (`hermes` CLI or Desktop installer), then
2. Launch through familia with `--client desktop` or `--client webapp` so the
   graph model wiring and `HERMES_HOME` stay familia-owned.

Linux upstream Desktop packaging includes AppImage/deb/rpm from the Hermes
checkout (`npm run dist:linux` in `apps/desktop`); published release legs may
vary — check upstream docs for the current matrix.

## FreeBSD (ordinary client port notes)

Native Hermes Desktop (Electron) targets **macOS / Windows / Linux**. FreeBSD
is not an Electron flagship for familia.

On FreeBSD today:

- **CLI** — `hermes-agent` via ports / `HERMES_BIN` (already resolved in
  `scripts/hermes_harness.py`; see #124).
- **Webapp** — when the installed Hermes build ships `webapp`, use
  `--client webapp` and open the one-use link in a browser (upstream documents
  BSD/illumos link-file behaviour for non-loopback open).

No familia FreeBSD Electron port is required for this track.

## Related

- `scripts/hermes.sh`, `scripts/hermes_modes.py`, `scripts/hermes_harness.py`
- [commands.md](commands.md) (Agents / hermes menu rows — CLI today; Desktop /
  Webapp menu rows deferred so Continuity’s front door is not collided)
- [packaging/README.md](../packaging/README.md) (familia AppImage ≠ Hermes Desktop; FreeBSD port notes)
- [appimage.md](appimage.md), [escalation.md](escalation.md)
- Issue [#142](https://github.com/brianreborn/familia/issues/142)
