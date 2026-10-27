# familia AppImage (Linux, single-click)

Milestone Linux builds prefer an **`.AppImage`** over a shell one-liner: download, mark executable (or double-click via the file manager), and the interactive **terminal menu** starts. No `curl | sh` required for packaging; a terminal is used for the menu.

The classic installers under `install/linux/install.sh` remain supported; AppImage is the milestone artifact.

## Get one

1. Download `familia-<version>-x86_64.AppImage` from the GitHub Release assets (or build locally below).
2. Make it executable once (some file managers prompt): right-click → Permissions → Allow executing, **or**  
   `chmod +x familia-*-x86_64.AppImage`
3. Run the file (or double-click if your desktop launches AppImages in a terminal). The familia menu starts.

First launch copies a writable checkout to `~/.local/share/familia/appimage-checkout` so graph edits and `familia sync` persist (the AppImage itself is read-only squashfs). Override with `FAMILIA_HOME=…`, or set `FAMILIA_APPIMAGE_RO=1` to run purely from the image.

## Terminal / CLI (optional)

```sh
./familia-*-x86_64.AppImage --menu
./familia-*-x86_64.AppImage --cli help
./familia-*-x86_64.AppImage --cli sync --dry-run
FAMILIA_MODE=cli ./familia-*-x86_64.AppImage validate
```

## Build on this machine

```sh
./scripts/build_appimage.sh
./scripts/build_appimage.sh --out dist/familia-milestone-x86_64.AppImage
```

Stages `packaging/appimage/` (`AppRun`, `.desktop`, logo), bundles the repo (excluding `.git` and `*.gguf`), runs **appimagetool**. Host packages `file` and `squashfs-tools` help packing; without them the script falls back to `dist/*.AppDir.tar.gz` (extract → `./AppRun`).

## What it is / is not

| Is | Is not |
|----|--------|
| Single-file Linux entry to menu + CLI | A FreeBSD/Windows package |
| Bundled familia scripts + menu | Pre-bundled multi-GiB GGUF weights |
| Milestone release asset alongside `.sh` installers | A replacement for angel’s source-built FreeBSD runtime |

See also: [install.md](./install.md), [QUICKSTART.md](../QUICKSTART.md).

## Not Hermes Desktop

This AppImage packages **familia**, not the upstream Hermes Desktop Electron app.
Client launch paths for Hermes Desktop / webapp: [hermes-clients.md](hermes-clients.md).
