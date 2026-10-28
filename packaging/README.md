# Packaging

Artifacts that ship **familia** (menu, CLI, graph helpers) — not Hermes Desktop.

| Path | What it packages |
|---|---|
| [`appimage/`](appimage/) | Linux **familia** AppImage (`AppRun`, desktop entry, icon). Build: `./scripts/build_appimage.sh`. Docs: [`docs/appimage.md`](../docs/appimage.md). |
| [`freebsd/`](freebsd/) | FreeBSD ports overlay for `sysutils/familia`. Ordinary familia port — not an Electron / Hermes Desktop port. |

## familia AppImage ≠ Hermes Desktop

| Artifact | Owner | Role |
|---|---|---|
| **familia** `.AppImage` | this repo (`packaging/appimage/`) | Single-file entry for familia (gum/menu + CLI). |
| **Hermes Desktop** installers | upstream [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | Native Electron app (`apps/desktop/`). |

**Do not vendor Electron into familia.** Install Hermes Desktop (or the `hermes` CLI) from upstream, then launch through familia:

```sh
scripts/hermes.sh --model coder --client desktop --yes
scripts/hermes.sh --model coder --client webapp --yes
```

Upstream Desktop packaging (AppImage / deb / rpm) is built from the Hermes tree
(`npm run dist:linux` in `apps/desktop`); see the
[Hermes Desktop guide](https://hermes-agent.nousresearch.com/docs/user-guide/desktop)
for the current release matrix.

Client wiring, FreeBSD ordinary-client notes, and the three equal frontend
surfaces (CLI / Desktop / Webapp): [`docs/hermes-clients.md`](../docs/hermes-clients.md).
