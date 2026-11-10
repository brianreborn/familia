#!/data/data/com.termux/files/usr/bin/sh
# familia Android smoke test (Termux). The phone is a THIN CLIENT: a Linux/Mac host runs
# Hermes (`scripts/hermes.sh --client webapp`, docs/hermes-clients.md) and the phone browser
# opens that host's webapp URL. No model, no guardian, no familia checkout on the phone.
# NON-PERSISTENT: everything goes in a throwaway prefix that is removed on exit.
# Built on qodesh Worker's prototype (install-android.sh). No sudo, never pipes a download into a shell.
#
# Usage:
#   sh familia-android-smoke.sh --commit SHA --host HOST --port PORT [--https] [--url-file FILE]
#                               [--local-inference] [--dry-run] [--keep]
#   sh familia-android-smoke.sh --remove
#   --commit     familia commit (40 hex) the license texts are fetched from (pin, never main)
#   --host/--port the Hermes webapp host (hostname, IPv4 or [IPv6]; port 1-65535)
#   --url-file   file holding the full one-use webapp link printed on the host; read from a
#                file so the token never lands in argv, shell history or this script's logs
#   --local-inference optional: fetch the cbl prebuilt llama.cpp for Android arm64 (pinned, sha256
#                checked), run llama-server --version, remove it. No model (choice by RAM: TBD).
# Steps: 1 fetch + verify license texts  2 show Llama 3.1 + Dolphin 3.0, type ACCEPT (no --yes)
#        3 check the host URL answers  4 open it in the phone browser  5 remove the prefix
# Office 3D: an upstream Hermes plugin for Linux/macOS hosts (docs/android-hermes.md); not on the phone.
set -eu
COMMIT=""; HOST=""; PORT=""; SCHEME=http; URL_FILE=""; LOCAL=0; DRY=""; KEEP=0; REMOVE=0
SMOKE_PREFIX=${FAMILIA_SMOKE_PREFIX:-${TMPDIR:-$HOME/.cache}/familia-smoke}
RAW=${FAMILIA_RAW_URL:-https://raw.githubusercontent.com/brianreborn/familia}
LIC_SUMS='bf2eac60b81e5c5f779fc3b4849d3bfacfd63f97f3eb68b44e9c6868c5801712  LLAMA-3.1-COMMUNITY-LICENSE.txt
f456a3f5b15ab588c84d06cf095a245bfee0bbc1620b48ed00af2cca4a711735  LLAMA-3.1-ACCEPTABLE-USE-POLICY.md
3f2524c574b24f59a654f845c8a3e927fe8f7f6dc5b89841e0dbc1fe85187534  DOLPHIN-3.0-MODEL-TERMS.txt'
# cbl = brianreborn/code-bootstraps-llama.cpp Android arm64 prebuilt. Mirrors the in-repo pin
# config/cbl-android-runtime.json (android-b12032-1); tests/test_android_smoke.py keeps them equal.
# Inline because this smoke test runs without a familia checkout on the phone.
CBL_URL=${FAMILIA_CBL_URL:-https://github.com/brianreborn/code-bootstraps-llama.cpp/releases/download/android-b12032-1}
CBL_TAR=llama-b12032-bin-android-arm64-cbl1.tar.gz
CBL_SHA=28612783f45e9ed247276f66880fc7077c0d3bedd592ce3c2361f6144ec27024

if [ -t 2 ] && [ -z "${NO_COLOR:-}" ]; then B=$(printf '\033[1m'); R=$(printf '\033[31m'); G=$(printf '\033[32m'); N=$(printf '\033[0m')
else B=""; R=""; G=""; N=""; fi
say() { echo "android-smoke: $*" >&2; }
ok()  { say "${G}OK${N} $*"; }
die() { say "${R}error${N}: $*"; exit 1; }
ascii() { if command -v iconv >/dev/null 2>&1; then iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null || LC_ALL=C tr -cd '\11\12\15\40-\176'; else LC_ALL=C tr -cd '\11\12\15\40-\176'; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --commit) shift; COMMIT=${1:-} ;;
    --host) shift; HOST=${1:-} ;;
    --port) shift; PORT=${1:-} ;;
    --https) SCHEME=https ;;
    --url-file) shift; URL_FILE=${1:-} ;;
    --local-inference) LOCAL=1 ;;
    --dry-run) DRY=1 ;;
    --keep) KEEP=1 ;;
    --remove) REMOVE=1 ;;
    --yes|-y|--accept-licenses) die "--yes is refused: licenses must be accepted by hand (#277)" ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown flag (see --help)" ;;
  esac
  shift
done

remove() {
  rm -rf "$SMOKE_PREFIX"; [ ! -e "$SMOKE_PREFIX" ] || die "could not remove $SMOKE_PREFIX"
  ok "removed $SMOKE_PREFIX"
}
case "$SMOKE_PREFIX" in ""|/|"$HOME"|"$HOME/") die "refusing unsafe prefix: '$SMOKE_PREFIX'" ;; esac
if [ "$REMOVE" = 1 ]; then remove; exit 0; fi

# Input validation (values are echoed only after they pass).
printf '%s' "$COMMIT" | grep -Eq '^[0-9a-f]{40}$' || die "--commit must be a full 40-hex commit (pin, never main)"
printf '%s' "$HOST" | grep -Eq '^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*|\[[0-9A-Fa-f:.]+\])$' \
  || die "--host must be a hostname, IPv4 address or [IPv6] address"
case "$PORT" in ''|*[!0-9]*) die "--port must be a number 1-65535" ;; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "--port must be a number 1-65535"
BASE="$SCHEME://$HOST:$PORT/"
LINK="$BASE"
if [ -n "$URL_FILE" ]; then
  [ -r "$URL_FILE" ] || die "--url-file not readable"
  LINK=$(head -n1 "$URL_FILE" | tr -d '\r')
  case "$LINK" in "$SCHEME://$HOST:$PORT/"*) ;; *) die "--url-file link does not start with $BASE (contents not shown)" ;; esac
  printf '%s' "$LINK" | grep -Eq '^[A-Za-z0-9._~:/?#@!$&()*+,;=%[-]+$' || die "--url-file link has unexpected characters (contents not shown)"
fi
say "host webapp: $BASE (any path/query/token from --url-file is never logged)"
case "$HOST" in localhost|127.*|\[::1\]) ;; *)
  [ "$SCHEME" = https ] || say "warning: plain http over the LAN; prefer --https or an ssh tunnel (ssh -L) to the host" ;; esac
[ -n "${TERMUX_VERSION:-}" ] || [ -n "$DRY" ] || die "not in Termux (use --dry-run elsewhere)"
[ -r /dev/tty ] || die "no terminal: an interactive license accept is required"
for c in curl sha256sum; do command -v "$c" >/dev/null 2>&1 || die "$c missing (pkg install curl coreutils)"; done

DL="$SMOKE_PREFIX/dl"; mkdir -p "$DL"
trap '[ "$KEEP" = 1 ] || remove' EXIT
fetch() { say "fetch $1"; curl -fsSL -o "$DL/$2" "$1" || die "download failed: $2"; }

# 1. license texts at the pinned commit
for f in LLAMA-3.1-COMMUNITY-LICENSE.txt LLAMA-3.1-ACCEPTABLE-USE-POLICY.md DOLPHIN-3.0-MODEL-TERMS.txt; do
  fetch "$RAW/$COMMIT/packaging/android/licenses/$f" "$f"
done
( cd "$DL" && printf '%s\n' "$LIC_SUMS" | sha256sum -c --quiet - ) || die "license text sha256 mismatch (deleted)"
ok "license texts sha256"

# 2. in-flow license accept (shown in full, ASCII). The host serves Dolphin3/Llama 3.1 models.
show() {
  { echo "------------------------------------------------------------"; echo "${B}$1${N}"; echo "Source: $2"
    echo "------------------------------------------------------------"; } >/dev/tty
  if command -v more >/dev/null 2>&1; then ascii <"$DL/$3" | more >/dev/tty; else ascii <"$DL/$3" >/dev/tty; fi
}
accept() {
  printf 'Type ACCEPT to accept %s (anything else stops): ' "$1" >/dev/tty
  ANS=""; IFS= read -r ANS </dev/tty || ANS=""
  [ "$ANS" = ACCEPT ] || die "$1 not accepted; stopping"
}
show "Llama 3.1 Community License Agreement" "https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE" LLAMA-3.1-COMMUNITY-LICENSE.txt
show "Llama 3.1 Acceptable Use Policy (part of the license)" "https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/USE_POLICY.md" LLAMA-3.1-ACCEPTABLE-USE-POLICY.md
accept "the Llama 3.1 Community License and Acceptable Use Policy"
show "Dolphin 3.0 model terms" "https://huggingface.co/cognitivecomputations/Dolphin3.0-Llama3.1-8B" DOLPHIN-3.0-MODEL-TERMS.txt
accept "the Dolphin 3.0 model terms"
ok "licenses accepted by hand"

# 3. optional local llama from cbl (no model)
if [ "$LOCAL" = 1 ]; then
  fetch "$CBL_URL/$CBL_TAR" "$CBL_TAR"
  GOT=$(sha256sum "$DL/$CBL_TAR" | cut -d' ' -f1)
  [ "$GOT" = "$CBL_SHA" ] || die "cbl tarball sha256 mismatch: got $GOT want $CBL_SHA"
  ok "cbl $CBL_TAR sha256"
  mkdir -p "$SMOKE_PREFIX/llama" && tar -xzf "$DL/$CBL_TAR" -C "$SMOKE_PREFIX/llama"
  SRV=$(find "$SMOKE_PREFIX/llama" -name llama-server -type f | head -n1)
  [ -n "$SRV" ] || die "llama-server not in $CBL_TAR"
  if [ -n "$DRY" ]; then say "[dry-run] would run llama-server --version"
  else "$SRV" --version >&2 && ok "cbl llama-server runs"; fi
  say "local model: TBD (chosen by RAM later); none downloaded"
fi

# 4. host reachability + open
CODE=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$BASE" 2>/dev/null || echo 000)
case "$CODE" in 2*|3*|401|403) ok "host webapp answers ($CODE) at $BASE" ;;
  *) die "host webapp did not answer at $BASE (http $CODE); on the host run: scripts/hermes.sh --client webapp" ;; esac
if [ -n "$DRY" ]; then say "[dry-run] would open the webapp in the phone browser"
elif command -v termux-open-url >/dev/null 2>&1; then termux-open-url "$LINK" && ok "opened in the phone browser"
else say "termux-open-url missing (pkg install termux-tools); open the link from ${URL_FILE:-$BASE} by hand"; fi
[ "$KEEP" = 1 ] && say "--keep: prefix left at $SMOKE_PREFIX; remove with: sh $0 --remove"
exit 0
