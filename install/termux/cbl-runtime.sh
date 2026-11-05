#!/bin/sh
# Download + verify a code-bootstraps-llama.cpp Android arm64 Termux prebuilt.
# Pin lives in config/cbl-android-runtime.json (tag + asset + sha256). Verify ONLY
# against that in-repo pin — never trust a release API digest as the authority.
# Default pin is android-b12032-1. Older android-b11969-1 is an explicit opt-in
# fallback only (FAMILIA_CBL_ANDROID_TAG + FAMILIA_CBL_ANDROID_SHA256); see
# fallback_opt_in in the pin file. Never pipe a download into a shell.
# Usage (sourced or executed):
#   sh install/termux/cbl-runtime.sh [--dry-run] [--prefix DIR]
# Env:
#   FAMILIA_PREFIX / PREFIX_DIR   install root (default: $HOME/familia)
#   FAMILIA_CBL_ANDROID_TAG + FAMILIA_CBL_ANDROID_SHA256
#     optional explicit override of the in-repo pin (BOTH required; loud warning).
#     FAMILIA_CBL_ANDROID_ASSET optional with the override.
#   FAMILIA_CBL_REPO / FAMILIA_CBL_API
#     refused unless FAMILIA_CBL_ANDROID_SHA256 is also set (pin bypass blocked).
# Offline: a previously verified unpack (marker matches pin sha) is reused without network.
# Prints the absolute path of the extracted runtime dir on stdout when successful
# (dry-run prints the would-be path). Status messages go to stderr.
set -eu

DRY=0
PREFIX_DIR=${FAMILIA_PREFIX:-${PREFIX_DIR:-$HOME/familia}}

say() { printf 'familia-cbl-runtime: %s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH='' cd -- "$HERE/../.." && pwd)
PIN_FILE=${FAMILIA_CBL_PIN_FILE:-$ROOT/config/cbl-android-runtime.json}
[ -f "$PIN_FILE" ] || die "missing pin file $PIN_FILE"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --prefix) shift; [ -n "${1:-}" ] || die "--prefix needs a directory"; PREFIX_DIR=$1 ;;
    -h|--help)
      sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
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

# Load pin (tag, asset, sha256, repo, download_url) from JSON.
eval "$(python3 - "$PIN_FILE" <<'PY'
import json, shlex, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
for k in ("repo", "tag", "asset", "sha256", "download_url"):
    if not p.get(k):
        sys.stderr.write("familia-cbl-runtime: pin missing %s\n" % k)
        sys.exit(1)
    print("%s=%s" % (k.upper() if k != "download_url" else "PIN_URL", shlex.quote(str(p[k]))))
PY
)" || die "could not parse pin $PIN_FILE"
PIN_REPO=$REPO
PIN_TAG=$TAG
PIN_ASSET=$ASSET
PIN_SHA=$SHA256

# Overrides: REPO/API alone must not bypass the pin.
if [ -n "${FAMILIA_CBL_REPO:-}" ] || [ -n "${FAMILIA_CBL_API:-}" ]; then
  if [ -z "${FAMILIA_CBL_ANDROID_SHA256:-}" ]; then
    die "FAMILIA_CBL_REPO/API override refused without FAMILIA_CBL_ANDROID_SHA256 (and TAG). Pin is $PIN_FILE (tag=$PIN_TAG sha=${PIN_SHA}). Do not bypass the in-repo pin."
  fi
  say "WARNING: FAMILIA_CBL_REPO/API set with an explicit pin sha — verify the override yourself (loud warn)."
fi

if [ -n "${FAMILIA_CBL_ANDROID_TAG:-}" ] || [ -n "${FAMILIA_CBL_ANDROID_SHA256:-}" ]; then
  [ -n "${FAMILIA_CBL_ANDROID_TAG:-}" ] || die "FAMILIA_CBL_ANDROID_SHA256 set but FAMILIA_CBL_ANDROID_TAG missing"
  [ -n "${FAMILIA_CBL_ANDROID_SHA256:-}" ] || die "FAMILIA_CBL_ANDROID_TAG set but FAMILIA_CBL_ANDROID_SHA256 missing (explicit pin sha required)"
  case "${FAMILIA_CBL_ANDROID_SHA256}" in
    REPLACE*|replace*|"" ) die "FAMILIA_CBL_ANDROID_SHA256 looks unset/placeholder; refusing" ;;
  esac
  say "WARNING: overriding in-repo pin with FAMILIA_CBL_ANDROID_TAG=${FAMILIA_CBL_ANDROID_TAG} sha=${FAMILIA_CBL_ANDROID_SHA256} (was tag=$PIN_TAG sha=$PIN_SHA). Verify this yourself."
  TAG=$FAMILIA_CBL_ANDROID_TAG
  SHA=$FAMILIA_CBL_ANDROID_SHA256
  ANAME=${FAMILIA_CBL_ANDROID_ASSET:-}
  if [ -z "$ANAME" ]; then
    # Best-effort asset name from tag (android-bNNNN-N -> llama-bNNNN-bin-android-arm64-cbl1.tar.gz)
    ANAME=$(printf '%s' "$TAG" | sed -n 's/^android-\(b[0-9][0-9]*\)-[0-9][0-9]*$/llama-\1-bin-android-arm64-cbl1.tar.gz/p')
    [ -n "$ANAME" ] || die "could not infer asset name; set FAMILIA_CBL_ANDROID_ASSET"
  fi
  REPO=${FAMILIA_CBL_REPO:-$PIN_REPO}
  AURL=${FAMILIA_CBL_DOWNLOAD_URL:-https://github.com/$REPO/releases/download/$TAG/$ANAME}
else
  TAG=$PIN_TAG
  SHA=$PIN_SHA
  ANAME=$PIN_ASSET
  REPO=$PIN_REPO
  AURL=$PIN_URL
fi

DEST="$PREFIX_DIR/runtime/$TAG"
CURRENT="$PREFIX_DIR/runtime/current"
DL_DIR="$PREFIX_DIR/runtime/.download"
MARKER="$DEST/.familia-cbl-pin"

pin_matches() {
  [ -f "$MARKER" ] || return 1
  [ -x "$DEST/llama-server" ] || return 1
  got=$(awk -F= '/^sha256=/{print $2; exit}' "$MARKER" 2>/dev/null || true)
  [ "$got" = "$SHA" ]
}

if pin_matches; then
  say "runtime $TAG already verified at $DEST (offline ok; pin sha matches)"
  [ "$DRY" = 1 ] || ln -sfn "$TAG" "$CURRENT"
  printf '%s\n' "$DEST"
  exit 0
fi

# Stale unpack without matching marker: refuse to treat as verified.
if [ -x "$DEST/llama-server" ] && [ ! -f "$MARKER" ]; then
  say "found $DEST/llama-server without pin marker; will re-download and verify against pin"
fi

if [ "$DRY" = 1 ]; then
  say "[dry-run] pin file $PIN_FILE tag=$TAG asset=$ANAME sha=$SHA"
  say "[dry-run] would download $AURL to $DL_DIR/$ANAME"
  say "[dry-run] would verify sha256 against in-repo pin only, extract to $DEST, clean $DL_DIR"
  printf '%s\n' "$DEST"
  exit 0
fi

command -v curl >/dev/null 2>&1 || die "curl required"
command -v tar >/dev/null 2>&1 || die "tar required"
mkdir -p "$DL_DIR"
TGZ="$DL_DIR/$ANAME"

say "download $ANAME -> $TGZ (pin tag=$TAG)"
curl -fL --retry 3 -o "$TGZ" "$AURL" || die "download failed: $AURL (offline re-run needs a previously verified unpack under $DEST)"

GOT=$(sha256_of "$TGZ")
[ "$GOT" = "$SHA" ] || die "sha256 mismatch vs in-repo pin for $ANAME: got $GOT want $SHA (pin $PIN_FILE)"
say "sha256 ok vs pin ($GOT)"

# Extract into a temp dir then flatten so llama-server sits at $DEST/llama-server.
TMP=$(mktemp -d "${TMPDIR:-/tmp}/familia-cbl.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$TGZ" -C "$TMP"
S=$(find "$TMP" -name llama-server -type f | head -n 1)
[ -n "$S" ] || die "llama-server not found in $ANAME"
SRC=$(dirname "$S")
rm -rf "$DEST"
mkdir -p "$DEST"
if cp -pR "$SRC"/. "$DEST"/ 2>/dev/null; then
  :
else
  cp -R "$SRC"/. "$DEST"/ || die "copy into $DEST failed"
fi
[ -x "$DEST/llama-server" ] || chmod +x "$DEST/llama-server" || true
[ -x "$DEST/llama-server" ] || die "llama-server not executable at $DEST"
{
  printf 'tag=%s\n' "$TAG"
  printf 'asset=%s\n' "$ANAME"
  printf 'sha256=%s\n' "$SHA"
  printf 'pin_file=%s\n' "$PIN_FILE"
} > "$MARKER"
ln -sfn "$TAG" "$CURRENT"
# Clean download cache after a verified unpack (keep disk free on phones).
rm -rf "$DL_DIR"
say "installed $TAG -> $DEST (current -> $TAG); cleaned $DL_DIR"
printf '%s\n' "$DEST"
