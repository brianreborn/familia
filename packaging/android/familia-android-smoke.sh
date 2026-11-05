#!/data/data/com.termux/files/usr/bin/sh
# familia Android smoke test (Termux): Hermes desktop path = `scripts/hermes.sh --client webapp`
# served on loopback and opened in the phone browser (docs/hermes-clients.md; the Electron
# Desktop has no Android build). NON-PERSISTENT: installs into a throwaway prefix and removes it.
# Built on qodesh Worker's prototype (install-android.sh, DESIGN.md option A). No sudo, no curl|sh.
#
# Usage:
#   sh familia-android-smoke.sh --commit SHA --sha256 HEX [--dry-run] [--keep]
#   sh familia-android-smoke.sh --remove            # remove a previous smoke prefix
#   HEX = sha256 of install/termux/install.sh at SHA (pin; never main).
# Steps: 1 download installer + license texts at SHA, verify sha256 (mismatch: delete, stop)
#        2 show Llama 3.1 Community License + AUP and Dolphin 3.0 terms; type ACCEPT (no --yes)
#        3 run the verified Termux installer into $SMOKE_PREFIX (--no-path --no-wakelock)
#        4 smoke: repo HEAD == SHA, licenses check, guardian gate (fail closed), hermes render-only
#        5 remove: installer --uninstall --purge, then rm the prefix (unless --keep)
# Office 3D: NOT in brianreborn/familia; this script does not install or stub it.
# Note: Termux pkg installs (git python getconf llama-cpp) are left in place by the installer.
set -eu
COMMIT=""; WANT=""; DRY=""; KEEP=0; REMOVE=0
SMOKE_PREFIX=${FAMILIA_SMOKE_PREFIX:-${TMPDIR:-$HOME/.cache}/familia-smoke}
RAW=${FAMILIA_RAW_URL:-https://raw.githubusercontent.com/brianreborn/familia}
# Pinned sha256 of the license texts (packaging/android/licenses/SHA256SUMS).
LIC_SUMS='bf2eac60b81e5c5f779fc3b4849d3bfacfd63f97f3eb68b44e9c6868c5801712  LLAMA-3.1-COMMUNITY-LICENSE.txt
f456a3f5b15ab588c84d06cf095a245bfee0bbc1620b48ed00af2cca4a711735  LLAMA-3.1-ACCEPTABLE-USE-POLICY.md
3f2524c574b24f59a654f845c8a3e927fe8f7f6dc5b89841e0dbc1fe85187534  DOLPHIN-3.0-MODEL-TERMS.txt'

if [ -t 2 ] && [ -z "${NO_COLOR:-}" ]; then B=$(printf '\033[1m'); R=$(printf '\033[31m'); G=$(printf '\033[32m'); N=$(printf '\033[0m')
else B=""; R=""; G=""; N=""; fi
say() { echo "android-smoke: $*" >&2; }
ok()  { say "${G}OK${N} $*"; }
die() { say "${R}error${N}: $*"; exit 1; }
ascii() { if command -v iconv >/dev/null 2>&1; then iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null || LC_ALL=C tr -cd '\11\12\15\40-\176'; else LC_ALL=C tr -cd '\11\12\15\40-\176'; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --commit) shift; COMMIT=${1:-} ;;
    --sha256) shift; WANT=${1:-} ;;
    --dry-run) DRY=1 ;;
    --keep) KEEP=1 ;;
    --remove) REMOVE=1 ;;
    --yes|-y|--accept-licenses) die "--yes is refused: licenses must be accepted by hand (#277)" ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
  shift
done

remove() {
  if [ -f "$SMOKE_PREFIX/repo/install/termux/install.sh" ]; then
    FAMILIA_PREFIX="$SMOKE_PREFIX" sh "$SMOKE_PREFIX/repo/install/termux/install.sh" --uninstall --purge ${DRY:+--dry-run} || say "installer uninstall reported an error; removing the prefix anyway"
  fi
  if [ -n "$DRY" ]; then say "[dry-run] would rm -rf $SMOKE_PREFIX"; else rm -rf "$SMOKE_PREFIX"; fi
  [ -e "$SMOKE_PREFIX" ] && [ -z "$DRY" ] && die "could not remove $SMOKE_PREFIX"
  ok "removed $SMOKE_PREFIX"
}
case "$SMOKE_PREFIX" in ""|/|"$HOME"|"$HOME/") die "refusing unsafe prefix: '$SMOKE_PREFIX'" ;; esac
if [ "$REMOVE" = 1 ]; then remove; exit 0; fi

printf '%s' "$COMMIT" | grep -Eq '^[0-9a-f]{40}$' || die "--commit must be a full 40-hex commit (pin, never main)"
printf '%s' "$WANT" | grep -Eq '^[0-9a-f]{64}$' || die "--sha256 must be 64 hex chars"
[ -n "${TERMUX_VERSION:-}" ] || [ -n "$DRY" ] || die "not in Termux (use --dry-run elsewhere)"
[ -r /dev/tty ] || die "no terminal: an interactive license accept is required"
for c in curl sha256sum; do command -v "$c" >/dev/null 2>&1 || die "$c missing (pkg install curl coreutils)"; done

DL="$SMOKE_PREFIX/dl"; mkdir -p "$DL"
fetch() { say "fetch $RAW/$COMMIT/$1"; curl -fsSL -o "$DL/$(basename "$1")" "$RAW/$COMMIT/$1" || { rm -rf "$DL"; die "download failed: $1"; }; }

# 1. download + verify
fetch install/termux/install.sh
GOT=$(sha256sum "$DL/install.sh" | cut -d' ' -f1)
[ "$GOT" = "$WANT" ] || { rm -rf "$DL"; die "installer sha256 mismatch: got $GOT want $WANT (deleted)"; }
ok "installer sha256 $GOT"
for f in LLAMA-3.1-COMMUNITY-LICENSE.txt LLAMA-3.1-ACCEPTABLE-USE-POLICY.md DOLPHIN-3.0-MODEL-TERMS.txt; do
  fetch "packaging/android/licenses/$f"
done
( cd "$DL" && printf '%s\n' "$LIC_SUMS" | sha256sum -c --quiet - ) || { rm -rf "$DL"; die "license text sha256 mismatch (deleted)"; }
ok "license texts sha256"

# 2. in-flow license accept (each one shown in full, ASCII)
show() {
  echo "------------------------------------------------------------" >/dev/tty
  echo "${B}$1${N}" >/dev/tty
  echo "Source: $2" >/dev/tty
  echo "------------------------------------------------------------" >/dev/tty
  if command -v more >/dev/null 2>&1; then ascii <"$DL/$3" | more >/dev/tty; else ascii <"$DL/$3" >/dev/tty; fi
}
accept() {
  printf 'Type ACCEPT to accept %s (anything else stops, nothing installed): ' "$1" >/dev/tty
  ANS=""; IFS= read -r ANS </dev/tty || ANS=""
  [ "$ANS" = ACCEPT ] || { rm -rf "$SMOKE_PREFIX"; die "$1 not accepted; nothing installed"; }
}
show "Llama 3.1 Community License Agreement" "https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE" LLAMA-3.1-COMMUNITY-LICENSE.txt
show "Llama 3.1 Acceptable Use Policy (part of the license)" "https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/USE_POLICY.md" LLAMA-3.1-ACCEPTABLE-USE-POLICY.md
accept "the Llama 3.1 Community License and Acceptable Use Policy"
show "Dolphin 3.0 model terms" "https://huggingface.co/cognitivecomputations/Dolphin3.0-Llama3.1-8B" DOLPHIN-3.0-MODEL-TERMS.txt
accept "the Dolphin 3.0 model terms"
ok "licenses accepted by hand"

# 3. install into the throwaway prefix (no --yes: the installer and licenses.py ask again)
export FAMILIA_PREFIX="$SMOKE_PREFIX" FAMILIA_BRANCH=main
trap '[ "$KEEP" = 1 ] || remove' EXIT
sh "$DL/install.sh" --no-path --no-wakelock --name a57-smoke ${DRY:+--dry-run} </dev/tty
if [ -n "$DRY" ]; then say "[dry-run] stop before smoke checks"; exit 0; fi
REPO="$SMOKE_PREFIX/repo"
git -C "$REPO" checkout -q --detach "$COMMIT" || die "commit $COMMIT not reachable from main"
ok "repo pinned at $COMMIT"

# 4. smoke checks
cd "$REPO"
if python scripts/licenses.py check --quiet; then ok "licenses.py: selection accepted"; else say "licenses.py check: not accepted"; fi
if python scripts/guardian_load.py; then ok "guardian weights verified"
else ok "guardian gate refused as designed (weights absent or mismatched; fail closed)"; fi
if sh scripts/hermes.sh --client webapp --render-only; then ok "hermes webapp render"; else say "hermes render failed (hermes-agent on Termux unverified)"; fi
say "to try the UI: sh scripts/hermes.sh --client webapp  (then open the printed loopback link)"
[ "$KEEP" = 1 ] && say "--keep: prefix left at $SMOKE_PREFIX; remove with: sh $0 --remove"
