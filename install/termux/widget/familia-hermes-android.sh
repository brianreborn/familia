#!/data/data/com.termux/files/usr/bin/sh
# Termux:Widget one-tap entry for Hermes Android (webapp-first).
# A tap launches the already-installed app (Hermes webapp + familia-start).
# It does NOT accept licenses for you — if the license selection changed, run
# install/termux/install-hermes-android.sh in a Termux terminal and accept there.
# Install: copy or symlink this file into ~/.shortcuts/ (Termux:Widget looks there).
#   mkdir -p ~/.shortcuts
#   ln -sf "$HOME/familia/repo/install/termux/widget/familia-hermes-android.sh" \
#          ~/.shortcuts/familia-hermes-android
# Then add the Termux:Widget on the home screen and tap "familia-hermes-android".
# Never passes --yes. No sudo. Does not sideload an APK (see packaging/android/README.md).
set -eu

# Resolve $0 through symlinks so a ~/.shortcuts link still finds the repo copy.
SOURCE=$0
while [ -L "$SOURCE" ]; do
  DIR=$(CDPATH='' cd -- "$(dirname -- "$SOURCE")" && pwd)
  LINK=$(readlink -- "$SOURCE" 2>/dev/null || readlink "$SOURCE")
  case "$LINK" in
    /*) SOURCE=$LINK ;;
    *) SOURCE="$DIR/$LINK" ;;
  esac
done
HERE=$(CDPATH='' cd -- "$(dirname -- "$SOURCE")" && pwd)

PREFIX_DIR="${FAMILIA_PREFIX:-$HOME/familia}"
REPO="${PREFIX_DIR}/repo"
SCRIPT="$REPO/install/termux/install-hermes-android.sh"

# Prefer the known prefix install; then sibling of this (resolved) file.
if [ ! -f "$SCRIPT" ]; then
  SCRIPT="$HERE/../install-hermes-android.sh"
fi
# ~/.shortcuts copy (not a symlink): walk up from HERE looking for familia layout,
# then fall back to the known prefix paths above.
if [ ! -f "$SCRIPT" ]; then
  for cand in \
      "$HERE/../install-hermes-android.sh" \
      "$PREFIX_DIR/repo/install/termux/install-hermes-android.sh" \
      "$HOME/familia/repo/install/termux/install-hermes-android.sh"
  do
    if [ -f "$cand" ]; then SCRIPT=$cand; break; fi
  done
fi
[ -f "$SCRIPT" ] || {
  echo "familia-hermes-android: missing install-hermes-android.sh (expected under $PREFIX_DIR/repo or beside this script). Run the Termux installer first." >&2
  exit 1
}

# Strip any --yes / -y the caller tried to sneak in — widget taps never auto-accept.
FILTERED=""
for a in "$@"; do
  case "$a" in
    --yes|-y) echo "familia-hermes-android: ignoring $a (widget taps do not accept licenses)" >&2 ;;
    *) FILTERED="$FILTERED $a" ;;
  esac
done
# shellcheck disable=SC2086
set -- $FILTERED

# Already installed? Launch only — do not re-run the full install, and never --yes.
if [ -x "$PREFIX_DIR/runtime/current/llama-server" ] \
   && { [ -x "${PREFIX:-/data/data/com.termux/files/usr}/bin/familia-start" ] \
        || [ -x "$PREFIX_DIR/bin/familia-start" ]; }; then
  exec sh "$SCRIPT" --launch-only "$@"
fi
exec sh "$SCRIPT" "$@"
