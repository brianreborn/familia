# familia AppImage packaging bits

| File | Role |
|---|---|
| `AppRun` | Entry: terminal menu by default; `--cli` for a one-shot command |
| `familia.desktop` | Desktop entry for AppImage tooling |
| `familia.svg` | Icon |

Build with `./scripts/build_appimage.sh` from a familia checkout. See [docs/appimage.md](../../docs/appimage.md).

## Not Hermes Desktop

This directory stages the **familia** AppImage only. Hermes Desktop Electron
installers come from upstream NousResearch/hermes-agent — see
[`../README.md`](../README.md) and [`docs/hermes-clients.md`](../../docs/hermes-clients.md).
