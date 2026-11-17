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
# Charm's published checksums.txt for gum v2.0.2. FAMILIA_GUM_VERSION cannot
# replace this pin, and FAMILIA_GUM_SHA256 cannot replace the hash.
PINNED_GUM_VERSION=2.0.2
pinned_sha() {
  case "$1" in
    gum_2.0.2_Linux_x86_64.tar.gz) printf '%s\n' d842e06d93dbed90af48cb8dd10698db6f22e331fc40346bb37bbc753109edc2 ;;
    gum_2.0.2_Linux_arm64.tar.gz) printf '%s\n' 8ebf8b54ec1e8c81f2bb58b59ff9b70998186a4d11375f0cf357b80e0ccfa1d5 ;;
    gum_2.0.2_Linux_armv6.tar.gz) printf '%s\n' 3589848314d33adc47b1852774d10808dd7c0c055f71b09a2cc60b6887429454 ;;
    gum_2.0.2_Linux_armv7.tar.gz) printf '%s\n' a7ee9b68052e401c47335982fec7fc1d246868abfe6b542654432ee2df7a8141 ;;
    gum_2.0.2_Linux_i386.tar.gz) printf '%s\n' 43332d42cf809434c884a51ff7f0c624e2c8c5fc2585f5153845ff691b8f45a4 ;;
    gum_2.0.2_Darwin_x86_64.tar.gz) printf '%s\n' 5374966c7c7199ea879fcaa525ddc6d447a098d3d35496e430a9a1ef38d30485 ;;
    gum_2.0.2_Darwin_arm64.tar.gz) printf '%s\n' 4777a69b1170b8db23c95d5889fb32186cfda1a3ac950d339aa17e3513633890 ;;
    gum_2.0.2_Freebsd_x86_64.tar.gz) printf '%s\n' 59ed7da50a3a83070d689ce188c093314273fab8acd48bd4f40b8159aaedbca7 ;;
    gum_2.0.2_Freebsd_arm64.tar.gz) printf '%s\n' 2d34b415b5957f0b3232ab00c296c98fb7ae015c12c43048b2003c369e830eab ;;
    gum_2.0.2_Freebsd_armv7.tar.gz) printf '%s\n' 3ac6b1f0bbac98701164eb29ca939e1290878d9c0dd873d119292cc0d1f46d3b ;;
    gum_2.0.2_Freebsd_armv6.tar.gz) printf '%s\n' c68357195e2e710305c7f909dbafd93285e0337c9c9aaacd606bed42e5f1a6eb ;;
    gum_2.0.2_Freebsd_i386.tar.gz) printf '%s\n' ffdaba5473f849b04627a2a753fe71a8102d5c6a417091b326efeb7c8acd09ed ;;
    *) printf '\n' ;;
  esac
}
file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v sha256 >/dev/null 2>&1; then
    sha256 -q "$1"
  else
    python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
  fi
}
if [ "$VERSION" != "$PINNED_GUM_VERSION" ]; then
  die "FAMILIA_GUM_VERSION=$VERSION is not pinned $PINNED_GUM_VERSION; refusing to skip checksum verification"
fi
case "$URL" in
  https://github.com/charmbracelet/gum/releases/download/v${PINNED_GUM_VERSION}/*) ;;
  *) die "refusing non-https gum URL: $URL" ;;
esac
WANT_SHA=$(pinned_sha "$ASSET")
[ -n "$WANT_SHA" ] || die "no pinned sha256 for $ASSET"
if [ -n "${FAMILIA_GUM_SHA256:-}" ] && [ "$FAMILIA_GUM_SHA256" != "$WANT_SHA" ]; then
  die "FAMILIA_GUM_SHA256 does not match the pinned checksum; refusing the override"
fi

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
  say "[dry-run] would verify sha256 $WANT_SHA"
  say "[dry-run] would install gum -> $DEST (write temp, then mv -f)"
  [ "$BIN_ON_PATH" = 1 ] || say "[dry-run] then add to PATH: export PATH=\"$(show_dir "$BIN"):\$PATH\""
  exit 0
fi

# --yes is the installer path. A person at a terminal is asked, and the default is no.
# With no terminal and no --yes, do not download.
if [ "$YES" != 1 ]; then
  if [ ! -r /dev/tty ] || [ ! -t 0 ]; then
    say "not a terminal and --yes was not given; not downloading gum"
    exit 1
  fi
  printf 'install-gum: gum (Charm) missing; download %s into %s now? [y/N] ' "$ASSET" "$DEST" >&2
  read -r ans < /dev/tty || ans=n
  case "$ans" in y|Y|yes|YES) ;; *) say "skipped (legacy menu: ./familia --legacy-menu)"; exit 1 ;; esac
fi

command -v tar >/dev/null 2>&1 || die "tar is required to extract $ASSET"
TMP=$(umask 077; mktemp -d "${TMPDIR:-/tmp}/grz.XXXXXX") || die "mktemp failed"
trap 'rm -rf -- "$TMP"' EXIT; trap 'exit 130' INT HUP TERM

say "downloading $URL"
if command -v curl >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -fsSL --retry 3 --retry-delay 1 -o "$TMP/$ASSET" "$URL" || die "download failed (curl); try later or: ./familia --legacy-menu"
elif command -v wget >/dev/null 2>&1; then
  wget --https-only -q -O "$TMP/$ASSET" "$URL" || die "download failed (wget); try later or: ./familia --legacy-menu"
else
  die "need curl or wget to fetch gum (sh install/deps.sh --install)"
fi
GOT_SHA=$(file_sha256 "$TMP/$ASSET")
if [ "$GOT_SHA" != "$WANT_SHA" ]; then
  die "sha256 mismatch for $ASSET (got ${GOT_SHA:-empty}, want $WANT_SHA); not installing"
fi
say "sha256 ok"

tar -xzf "$TMP/$ASSET" -C "$TMP" || die "extract failed"
GUM_BIN=$(find "$TMP" -type f -name gum 2>/dev/null | head -n 1)
[ -n "$GUM_BIN" ] || die "no 'gum' binary inside $ASSET"
mkdir -p "$BIN"
STAGE=$DEST.tmp.$$
cp "$GUM_BIN" "$STAGE"
chmod 755 "$STAGE"
mv -f "$STAGE" "$DEST"
say "installed $DEST ($( "$DEST" --version 2>/dev/null | head -n1 || echo ok))"
path_hint
exit 0
