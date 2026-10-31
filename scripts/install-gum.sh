#!/bin/sh
# install-gum.sh: put Charm gum on this user's PATH (no sudo, no Go).
# Downloads a release binary into $XDG_BIN_HOME/gum (default ~/.local/bin/gum).
# Usage:
#   sh scripts/install-gum.sh              # install if missing
#   sh scripts/install-gum.sh --dry-run    # say what would happen
#   sh scripts/install-gum.sh --yes        # non-interactive (default for missing gum)
#   FAMILIA_GUM_VERSION=2.0.2 sh scripts/install-gum.sh   # pin (default 2.0.2)
# Termux: tries `pkg install gum` first, then the Linux release binary.
# Windows: this script prints a hint; use a Charm Windows zip or winget/scoop.
# Called from install.sh / install/linux/install.sh / install/termux/install.sh.
# Soft-fail friendly: exit 1 on download failure (callers warn and continue).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DRY=0
YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --yes|-y) YES=1 ;;
    -h|--help)
      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "install-gum: unknown argument '$1' (see --help)" >&2; exit 2 ;;
  esac
  shift
done

say() { echo "install-gum: $*" >&2; }
die() { say "error: $*"; exit 1; }

# Prefer user-local bin (same as familia_home.sh / install-cli.sh).
TERMUX=0
if [ -n "${TERMUX_VERSION:-}" ]; then TERMUX=1
else case "${PREFIX:-}" in */com.termux/*) TERMUX=1 ;; esac
fi
if [ "$TERMUX" = 1 ] && [ -n "${PREFIX:-}" ]; then
  BIN=${PREFIX}/bin
else
  case "${XDG_BIN_HOME:-}" in
    /*) BIN=$XDG_BIN_HOME ;;
    *) BIN=${HOME:-}/.local/bin ;;
  esac
fi
# Remember whether BIN was already on PATH before we prepend it (for the hint).
case ":${PATH:-}:" in *":$BIN:"*) BIN_ON_PATH=1 ;; *) BIN_ON_PATH=0 ;; esac
PATH="$BIN:${PATH:-}"
export PATH

if command -v gum >/dev/null 2>&1; then
  say "already on PATH: $(command -v gum) ($(gum --version 2>/dev/null | head -n1 || echo ok))"
  exit 0
fi

VERSION=${FAMILIA_GUM_VERSION:-2.0.2}
VERSION=${VERSION#v}

# Termux: prefer pkg when the index has gum (no GitHub fetch needed).
if [ "$TERMUX" = 1 ] && command -v pkg >/dev/null 2>&1; then
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would try: pkg install -y gum  (dest $BIN/gum)"
    say "[dry-run] fallback: Charm Linux release binary → $BIN/gum"
    exit 0
  fi
  if pkg search gum 2>/dev/null | grep -q '^gum'; then
    say "Termux: pkg install -y gum"
    if pkg install -y gum; then
      PATH="$BIN:${PATH:-}"; export PATH
      if command -v gum >/dev/null 2>&1; then
        say "installed via pkg: $(command -v gum)"
        exit 0
      fi
    fi
    say "pkg install gum did not put gum on PATH; trying Charm release binary"
  fi
fi

OS=$(uname -s 2>/dev/null || echo unknown)
ARCH=$(uname -m 2>/dev/null || echo unknown)
case "$OS" in
  Linux) ROS=Linux ;;
  Darwin) ROS=Darwin ;;
  FreeBSD) ROS=Freebsd ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    say "Windows: download gum from https://github.com/charmbracelet/gum/releases"
    say "  (e.g. gum_${VERSION}_Windows_x86_64.zip) into %LOCALAPPDATA%\\Programs\\familia\\bin"
    say "  or: winget install charmbracelet.gum / scoop install gum"
    say "Legacy menu without gum: familia.cmd -LegacyMenu"
    exit 1 ;;
  *) die "unsupported uname '$OS' (need Linux, Darwin, FreeBSD, or Termux)" ;;
esac
case "$ARCH" in
  x86_64|amd64) RARCH=x86_64 ;;
  aarch64|arm64) RARCH=arm64 ;;
  armv7l|armv7) RARCH=armv7 ;;
  armv6l|armv6) RARCH=armv6 ;;
  i386|i686) RARCH=i386 ;;
  *) die "unsupported arch '$ARCH'" ;;
esac

ASSET="gum_${VERSION}_${ROS}_${RARCH}.tar.gz"
URL="https://github.com/charmbracelet/gum/releases/download/v${VERSION}/${ASSET}"
DEST=$BIN/gum

show_dir() { case "$1" in "$HOME"/*) printf '$HOME/%s' "${1#"$HOME"/}" ;; *) printf '%s' "$1" ;; esac; }
path_hint() {
  if [ "$BIN_ON_PATH" = 1 ]; then say "$(show_dir "$BIN") is on PATH"
  else
    say "$(show_dir "$BIN") is not on PATH yet. Add:"
    echo "    export PATH=\"$(show_dir "$BIN"):\$PATH\"" >&2
  fi
}

if [ "$DRY" = 1 ]; then
  say "[dry-run] would download $URL"
  say "[dry-run] would install gum → $DEST"
  [ "$BIN_ON_PATH" = 1 ] || say "[dry-run] then add to PATH: export PATH=\"$(show_dir "$BIN"):\$PATH\""
  exit 0
fi

# Non-interactive by default when gum is missing (install.sh --yes / a downloaded installer run without a terminal).
# Only ask when a TTY is present and --yes was not passed.
if [ "$YES" != 1 ] && [ -r /dev/tty ] && [ -t 0 ]; then
  printf 'install-gum: gum (Charm) missing; download %s into %s now? [Y/n] ' "$ASSET" "$DEST" >&2
  read -r ans < /dev/tty || ans=y
  case "$ans" in ''|y|Y|yes|YES) ;; *) say "skipped (legacy menu: ./familia --legacy-menu)"; exit 1 ;; esac
fi

command -v tar >/dev/null 2>&1 || die "tar is required to extract $ASSET"
TMP=$(umask 077; mktemp -d "${TMPDIR:-/tmp}/grz.XXXXXX") || die "mktemp failed"
trap 'rm -rf "$TMP"' EXIT INT HUP TERM

say "downloading $URL"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL --retry 3 --retry-delay 1 -o "$TMP/$ASSET" "$URL" || die "download failed (curl); try later or: ./familia --legacy-menu"
elif command -v wget >/dev/null 2>&1; then
  wget -q -O "$TMP/$ASSET" "$URL" || die "download failed (wget); try later or: ./familia --legacy-menu"
else
  die "need curl or wget to fetch gum (sh install/deps.sh --install)"
fi

tar -xzf "$TMP/$ASSET" -C "$TMP" || die "extract failed"
GUM_BIN=$(find "$TMP" -type f -name gum 2>/dev/null | head -n 1)
[ -n "$GUM_BIN" ] || die "no 'gum' binary inside $ASSET"
mkdir -p "$BIN"
cp "$GUM_BIN" "$DEST"
chmod 755 "$DEST"
say "installed $DEST ($( "$DEST" --version 2>/dev/null | head -n1 || echo ok))"
path_hint
exit 0
