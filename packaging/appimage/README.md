# packaging/appimage

| File | Role |
|------|------|
| `AppRun` | Entry: panel by default; `--menu` / `--cli` for terminal |
| `familia.desktop` | FreeDesktop launcher + categories |
| Icon | `assets/logo/familia-arbol-mark.png` (copied as `familia.png` at build) |

Build: `./scripts/build_appimage.sh` → `dist/*.AppImage`. Docs: `docs/appimage.md`.
