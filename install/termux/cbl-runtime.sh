#!/bin/sh
# Download + verify a code-bootstraps-llama.cpp Android arm64 Termux prebuilt.
# Prefer android-b12032-1; fall back to android-b11969-1 when that tag has no asset yet.
# Never pipe a download into a shell. Download to a named file, verify sha256, then extract.
# Usage (sourced or executed):
#   sh install/termux/cbl-runtime.sh [--dry-run] [--prefix DIR]
# Env:
#   FAMILIA_PREFIX / PREFIX_DIR   install root (default: $HOME/familia)
#   FAMILIA_CBL_ANDROID_TAG      force a release tag (skips prefer/fallback)
#   FAMILIA_CBL_REPO             owner/repo (default: brianreborn/code-bootstraps-llama.cpp)
#   FAMILIA_CBL_API              override releases API base
# Prints the absolute path of the extracted runtime dir on stdout when successful
# (dry-run prints the would-be path). Status messages go to stderr.
set -eu

DRY=0
PREFIX_DIR=${FAMILIA_PREFIX:-${PREFIX_DIR:-$HOME/familia}}
REPO=${FAMILIA_CBL_REPO:-brianreborn/code-bootstraps-llama.cpp}
API=${FAMILIA_CBL_API:-https://api.github.com/repos/$REPO/releases}
PREFER_TAG=${FAMILIA_CBL_ANDROID_TAG:-}
FALLBACK_TAG=android-b11969-1
PRIMARY_TAG=android-b12032-1

say() { printf 'familia-cbl-runtime: %s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --prefix) shift; [ -n "${1:-}" ] || die "--prefix needs a directory"; PREFIX_DIR=$1 ;;
    -h|--help)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
  shift
done

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else die "need sha256sum or shasum"; fi
}

# Resolve tag + asset name + url + sha256 (from API digest and/or SHA256SUMS).
# Prefer PREFER_TAG if set; else PRIMARY_TAG if it has an android arm64 tarball; else FALLBACK_TAG.
pick_release() {
  tags=""
  if [ -n "$PREFER_TAG" ]; then
    tags=$PREFER_TAG
  else
    tags="$PRIMARY_TAG $FALLBACK_TAG"
  fi
  for tag in $tags; do
    url="$API/tags/$tag"
    say "querying $url"
    json=$(curl -fsSL -H 'Accept: application/vnd.github+json' "$url" 2>/dev/null) || {
      say "tag $tag not reachable; trying next"
      continue
    }
    sel=$(printf '%s' "$json" | python3 -c '
import json, re, sys
j = json.load(sys.stdin)
assets = j.get("assets") or []
hit = [a for a in assets if re.search(r"llama-b[0-9]+-bin-android-arm64.*\.tar\.gz$", a.get("name", ""))]
if not hit:
    sys.exit(0)
a = hit[0]
d = a.get("digest") or ""
sha = d.split(":", 1)[1] if d.startswith("sha256:") else ""
print(j.get("tag_name", ""), a["name"], a["browser_download_url"], sha)
') || true
    if [ -n "$sel" ]; then
      # shellcheck disable=SC2086
      set -- $sel
      TAG=$1; ANAME=$2; AURL=$3; SHA=${4:-}
      return 0
    fi
    say "tag $tag has no android-arm64 tarball asset; trying next"
  done
  return 1
}

pick_release || die "no cbl Android arm64 release found (tried ${PREFER_TAG:-$PRIMARY_TAG then $FALLBACK_TAG})"
[ -n "$SHA" ] || say "API digest missing for $ANAME; will require SHA256SUMS match"

DEST="$PREFIX_DIR/runtime/$TAG"
CURRENT="$PREFIX_DIR/runtime/current"
DL_DIR="$PREFIX_DIR/runtime/.download"
SUMS_URL="https://github.com/$REPO/releases/download/$TAG/SHA256SUMS"

if [ -x "$DEST/llama-server" ]; then
  say "runtime $TAG already installed at $DEST"
  [ "$DRY" = 1 ] || ln -sfn "$TAG" "$CURRENT"
  printf '%s\n' "$DEST"
  exit 0
fi

if [ "$DRY" = 1 ]; then
  say "[dry-run] would download $AURL to $DL_DIR/$ANAME"
  say "[dry-run] would download $SUMS_URL to $DL_DIR/SHA256SUMS.$TAG"
  say "[dry-run] would verify sha256${SHA:+ (api $SHA)} and extract to $DEST"
  printf '%s\n' "$DEST"
  exit 0
fi

command -v curl >/dev/null 2>&1 || die "curl required"
command -v tar >/dev/null 2>&1 || die "tar required"
mkdir -p "$DL_DIR" "$DEST"
TGZ="$DL_DIR/$ANAME"
SUMS="$DL_DIR/SHA256SUMS.$TAG"

say "download $ANAME -> $TGZ"
curl -fL --retry 3 -o "$TGZ" "$AURL" || die "download failed: $AURL"
say "download SHA256SUMS -> $SUMS"
curl -fL --retry 3 -o "$SUMS" "$SUMS_URL" || die "SHA256SUMS download failed: $SUMS_URL"

GOT=$(sha256_of "$TGZ")
SUM_LINE=$(awk -v f="$ANAME" '$2 == f {print $1; exit}' "$SUMS")
[ -n "$SUM_LINE" ] || die "SHA256SUMS has no entry for $ANAME"
[ "$GOT" = "$SUM_LINE" ] || die "sha256 mismatch vs SHA256SUMS for $ANAME: got $GOT want $SUM_LINE"
if [ -n "$SHA" ] && [ "$GOT" != "$SHA" ]; then
  die "sha256 mismatch vs API digest for $ANAME: got $GOT want $SHA"
fi
say "sha256 ok ($GOT)"

# Extract into a temp dir then flatten so llama-server sits at $DEST/llama-server.
TMP=$(mktemp -d "${TMPDIR:-/tmp}/familia-cbl.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$TGZ" -C "$TMP"
S=$(find "$TMP" -name llama-server -type f | head -n 1)
[ -n "$S" ] || die "llama-server not found in $ANAME"
SRC=$(dirname "$S")
# Copy contents (including .so next to the binary) into DEST.
# POSIX: no cp -a required; preserve mode with cp -p when available.
if cp -pR "$SRC"/. "$DEST"/ 2>/dev/null; then
  :
else
  cp -R "$SRC"/. "$DEST"/ || die "copy into $DEST failed"
fi
[ -x "$DEST/llama-server" ] || chmod +x "$DEST/llama-server" || true
[ -x "$DEST/llama-server" ] || die "llama-server not executable at $DEST"
ln -sfn "$TAG" "$CURRENT"
say "installed $TAG -> $DEST (current -> $TAG)"
printf '%s\n' "$DEST"
