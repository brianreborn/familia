#!/usr/bin/env bash
# Build a Linux x86_64 AppImage for familia (milestone / single-click, no CLI required).
#
# Usage (from repo root):
#   ./scripts/build_appimage.sh
#   ./scripts/build_appimage.sh --out dist/familia-dev-x86_64.AppImage
#   ./scripts/build_appimage.sh --skip-tool-download
#
# Produces: dist/familia-<version>-x86_64.AppImage
# Needs: bash, rsync or cp, curl/wget for appimagetool; `file` + squashfs-tools for packing.
# If appimagetool cannot pack (missing file(1), no FUSE), writes dist/*.AppDir.tar.gz instead.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

OUT=""
SKIP_DL=0
ARCH=x86_64
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT=$2; shift 2 ;;
    --skip-tool-download) SKIP_DL=1; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

VERSION=$(git describe --tags --always --dirty 2>/dev/null || echo "0.0.0-dev")
VERSION=${VERSION#v}
OUT=${OUT:-"$ROOT/dist/familia-${VERSION}-${ARCH}.AppImage"}
APPDIR=$(mktemp -d "${TMPDIR:-/tmp}/familia-AppDir.XXXXXX")
STAGED=""
cleanup() {
  rm -rf "$APPDIR"
  [ -n "$STAGED" ] && rm -rf "$STAGED"
}
trap cleanup EXIT

echo "familia AppImage: staging AppDir → $APPDIR"
mkdir -p "$APPDIR/usr/share/familia" "$APPDIR/usr/bin" \
  "$APPDIR/usr/share/icons/hicolor/256x256/apps" "$APPDIR/usr/share/applications"

if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude '.git' --exclude 'dist' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude '.venv' --exclude 'node_modules' --exclude '*.gguf' \
    --exclude 'green-roomz/data' --exclude 'agent-tools' \
    "$ROOT/" "$APPDIR/usr/share/familia/"
else
  tar -C "$ROOT" --exclude=.git --exclude=dist --exclude='*.gguf' -cf - . \
    | tar -C "$APPDIR/usr/share/familia" -xf -
fi

install -m 0755 "$ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"
install -m 0644 "$ROOT/packaging/appimage/familia.desktop" "$APPDIR/familia.desktop"
install -m 0644 "$ROOT/packaging/appimage/familia.desktop" "$APPDIR/usr/share/applications/familia.desktop"

ICON_SRC="$ROOT/assets/logo/familia-arbol-mark.png"
if [ -f "$ICON_SRC" ]; then
  install -m 0644 "$ICON_SRC" "$APPDIR/familia.png"
  install -m 0644 "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/familia.png"
fi

cat > "$APPDIR/usr/bin/familia" << 'SH'
#!/bin/sh
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/../share/familia" && pwd)
exec "$HERE/familia" "$@"
SH
chmod +x "$APPDIR/usr/bin/familia"

# Provide a minimal `file` shim if missing (appimagetool requires it for MIME sniff).
if ! command -v file >/dev/null 2>&1; then
  mkdir -p "$APPDIR/.bundle-bin"
  cat > "$APPDIR/.bundle-bin/file" << 'SH'
#!/bin/sh
# Minimal shim so appimagetool can run without distro `file` package.
# Reports ELF for executables; otherwise "data".
for f in "$@"; do
  case "$f" in -*) continue ;; esac
  if [ -f "$f" ] && head -c 4 "$f" 2>/dev/null | grep -q $'\x7fELF'; then
    echo "$f: ELF"
  else
    echo "$f: data"
  fi
done
exit 0
SH
  chmod +x "$APPDIR/.bundle-bin/file"
  export PATH="$APPDIR/.bundle-bin:$PATH"
  # Also put shim in cache for host-side appimagetool child processes
  mkdir -p "$HOME/.cache/familia/bin"
  cp "$APPDIR/.bundle-bin/file" "$HOME/.cache/familia/bin/file"
  export PATH="$HOME/.cache/familia/bin:$PATH"
fi

TOOL=""
if command -v appimagetool >/dev/null 2>&1; then
  TOOL=$(command -v appimagetool)
elif [ -x "$HOME/.cache/familia/appimagetool-${ARCH}.AppImage" ]; then
  TOOL="$HOME/.cache/familia/appimagetool-${ARCH}.AppImage"
elif [ "$SKIP_DL" = 0 ]; then
  mkdir -p "$HOME/.cache/familia"
  URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  DEST="$HOME/.cache/familia/appimagetool-${ARCH}.AppImage"
  echo "familia AppImage: fetching appimagetool → $DEST"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$DEST" "$URL"
  else
    wget -q -O "$DEST" "$URL"
  fi
  chmod +x "$DEST"
  TOOL=$DEST
fi

mkdir -p "$(dirname -- "$OUT")"
pack_tar() {
  local tar_out="${OUT%.AppImage}.AppDir.tar.gz"
  STAGED=$(dirname -- "$APPDIR")/familia.AppDir
  rm -rf "$STAGED"
  cp -a "$APPDIR" "$STAGED"
  tar -C "$(dirname -- "$STAGED")" -czf "$tar_out" "$(basename -- "$STAGED")"
  echo "wrote $tar_out (extract and run ./AppRun; install file+squashfs-tools for a real .AppImage)"
}

if [ -n "$TOOL" ]; then
  echo "familia AppImage: packing with $TOOL"
  export ARCH
  export PATH="${HOME}/.cache/familia/bin:${PATH:-}"
  set +e
  APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT"
  rc=$?
  set -e
  if [ -f "$OUT" ] && [ -s "$OUT" ]; then
    chmod +x "$OUT"
    ls -lh "$OUT"
    echo "OK: $OUT (appimagetool exit $rc)"
    exit 0
  fi
  echo "familia AppImage: appimagetool failed (exit $rc); writing portable AppDir tarball instead" >&2
  pack_tar
  exit 1
fi

echo "familia AppImage: no appimagetool; writing portable AppDir tarball" >&2
pack_tar
exit 1
