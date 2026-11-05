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
#   FAMILIA_CBL_REPO / FAMILIA_CBL_API / FAMILIA_CBL_DOWNLOAD_URL / FAMILIA_CBL_PIN_FILE
#     each refused unless FAMILIA_CBL_ANDROID_SHA256 (+ TAG) is also set (pin bypass
#     blocked). PIN_FILE and DOWNLOAD_URL warn loudly when allowed with an explicit sha.
# Offline: a previously verified unpack (marker pin sha + size/mtime + sha256 of
# llama-server and every .so) is reused without network. Stale messages name the file.
# Prints the absolute path of the extracted runtime dir on stdout when successful
# (dry-run prints the would-be path). Status messages go to stderr.
set -eu

DRY=0
PREFIX_DIR=${FAMILIA_PREFIX:-${PREFIX_DIR:-$HOME/familia}}

say() { printf 'familia-cbl-runtime: %s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH='' cd -- "$HERE/../.." && pwd)
DEFAULT_PIN="$ROOT/config/cbl-android-runtime.json"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --prefix) shift; [ -n "${1:-}" ] || die "--prefix needs a directory"; PREFIX_DIR=$1 ;;
    -h|--help)
      sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
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

file_size() { wc -c < "$1" | tr -d ' '; }
file_mtime() {
  # Prefer GNU/BSD stat; fall back to ls.
  if stat -c %Y "$1" >/dev/null 2>&1; then stat -c %Y "$1"
  elif stat -f %m "$1" >/dev/null 2>&1; then stat -f %m "$1"
  else ls -l "$1" | awk '{print $6$7$8}'; fi
}

# Explicit override required for any pin-bypass env (REPO/API/DOWNLOAD_URL/PIN_FILE).
need_explicit_pin() {
  what=$1
  if [ -z "${FAMILIA_CBL_ANDROID_SHA256:-}" ] || [ -z "${FAMILIA_CBL_ANDROID_TAG:-}" ]; then
    die "$what refused without FAMILIA_CBL_ANDROID_TAG + FAMILIA_CBL_ANDROID_SHA256. Do not bypass the in-repo pin ($DEFAULT_PIN)."
  fi
}

PIN_FILE=$DEFAULT_PIN
if [ -n "${FAMILIA_CBL_PIN_FILE:-}" ]; then
  need_explicit_pin "FAMILIA_CBL_PIN_FILE"
  say "WARNING: FAMILIA_CBL_PIN_FILE=${FAMILIA_CBL_PIN_FILE} with explicit TAG+SHA256 — verify this pin yourself (loud warn)."
  PIN_FILE=$FAMILIA_CBL_PIN_FILE
fi
[ -f "$PIN_FILE" ] || die "missing pin file $PIN_FILE"

if [ -n "${FAMILIA_CBL_DOWNLOAD_URL:-}" ]; then
  need_explicit_pin "FAMILIA_CBL_DOWNLOAD_URL"
  say "WARNING: FAMILIA_CBL_DOWNLOAD_URL set with explicit TAG+SHA256 — verify the URL yourself (loud warn)."
fi
if [ -n "${FAMILIA_CBL_REPO:-}" ] || [ -n "${FAMILIA_CBL_API:-}" ]; then
  need_explicit_pin "FAMILIA_CBL_REPO/API"
  say "WARNING: FAMILIA_CBL_REPO/API set with an explicit pin sha — verify the override yourself (loud warn)."
fi

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
SERVER="$DEST/llama-server"

# Manifest of llama-server + every .so: size+mtime + sha256 (hash all .so files; skip GGUF).
write_runtime_manifest() {
  python3 - "$DEST" "$MARKER" "$TAG" "$ANAME" "$SHA" "$PIN_FILE" <<'PY'
import hashlib, os, sys
dest, marker, tag, asset, sha, pin = sys.argv[1:7]

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

rows = []
for name in sorted(os.listdir(dest)):
    path = os.path.join(dest, name)
    if not os.path.isfile(path):
        continue
    if name == "llama-server" or name.endswith(".so") or ".so." in name:
        st = os.stat(path)
        # Hash every .so (cheap). Also hash llama-server (not the big GGUF).
        digest = sha256_file(path)
        rows.append("%s %d %d %s" % (name, st.st_size, int(st.st_mtime), digest))
if not any(r.startswith("llama-server ") for r in rows):
    sys.stderr.write("familia-cbl-runtime: llama-server missing when writing manifest\n")
    sys.exit(1)
with open(marker, "w", encoding="utf-8") as f:
    f.write("tag=%s\n" % tag)
    f.write("asset=%s\n" % asset)
    f.write("sha256=%s\n" % sha)
    f.write("pin_file=%s\n" % pin)
    f.write("manifest_begin\n")
    for r in rows:
        f.write(r + "\n")
    f.write("manifest_end\n")
PY
}

pin_matches() {
  [ -f "$MARKER" ] || return 1
  [ -x "$SERVER" ] || return 1
  got=$(awk -F= '/^sha256=/{print $2; exit}' "$MARKER" 2>/dev/null || true)
  [ "$got" = "$SHA" ] || return 1
  # size+mtime first; then sha256 of every .so (+ llama-server; not the GGUF). Name the stale file.
  python3 - "$DEST" "$MARKER" <<'PY'
import hashlib, os, sys
dest, marker = sys.argv[1], sys.argv[2]

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

want = {}
inside = False
with open(marker, encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if line == "manifest_begin":
            inside = True
            continue
        if line == "manifest_end":
            inside = False
            break
        if not inside:
            continue
        parts = line.split()
        if len(parts) == 4:
            want[parts[0]] = (int(parts[1]), int(parts[2]), parts[3])
        elif len(parts) == 3:
            # legacy size+mtime-only marker: treat as stale so we rewrite with hashes
            sys.stderr.write("familia-cbl-runtime: stale marker format for %s (need sha256); will re-verify\n" % parts[0])
            sys.exit(1)
        else:
            sys.exit(1)
if "llama-server" not in want:
    sys.exit(1)
have_names = set()
for name in os.listdir(dest):
    path = os.path.join(dest, name)
    if not os.path.isfile(path):
        continue
    if not (name == "llama-server" or name.endswith(".so") or ".so." in name):
        continue
    have_names.add(name)
    st = os.stat(path)
    if name not in want:
        sys.stderr.write("familia-cbl-runtime: unexpected file %s not in marker; will re-verify\n" % name)
        sys.exit(1)
    wsize, wmtime, wsha = want[name]
    if st.st_size != wsize or int(st.st_mtime) != wmtime:
        sys.stderr.write("familia-cbl-runtime: stale marker for %s (size/mtime changed); will re-verify\n" % name)
        sys.exit(1)
    # Cheap hash of .so files and llama-server (not the big GGUF model).
    got = sha256_file(path)
    if got != wsha:
        sys.stderr.write("familia-cbl-runtime: stale marker for %s (sha256 mismatch); will re-verify\n" % name)
        sys.exit(1)
missing = set(want) - have_names
if missing:
    sys.stderr.write("familia-cbl-runtime: stale marker for %s (missing on disk); will re-verify\n" % sorted(missing)[0])
    sys.exit(1)
sys.exit(0)
PY
}

if pin_matches; then
  say "runtime $TAG already verified at $DEST (offline ok; pin sha + .so/llama-server hashes match)"
  [ "$DRY" = 1 ] || ln -sfn "$TAG" "$CURRENT"
  printf '%s\n' "$DEST"
  exit 0
fi

if [ -x "$SERVER" ] && [ -f "$MARKER" ]; then
  say "marker present but stale (see file named above) or pin sha mismatch; will re-download and verify"
elif [ -x "$SERVER" ] && [ ! -f "$MARKER" ]; then
  say "found $SERVER without pin marker; will re-download and verify against pin"
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
[ -x "$SERVER" ] || chmod +x "$SERVER" || true
[ -x "$SERVER" ] || die "llama-server not executable at $DEST"
write_runtime_manifest
ln -sfn "$TAG" "$CURRENT"
rm -rf "$DL_DIR"
say "installed $TAG -> $DEST (current -> $TAG); cleaned $DL_DIR"
printf '%s\n' "$DEST"
