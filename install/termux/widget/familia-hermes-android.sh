#!/data/data/com.termux/files/usr/bin/sh
# Termux:Widget one-tap entry for Hermes Android (webapp-first).
# Install: copy or symlink this file into ~/.shortcuts/ (Termux:Widget looks there).
#   mkdir -p ~/.shortcuts
#   ln -sf "$HOME/familia/repo/install/termux/widget/familia-hermes-android.sh" \
#          ~/.shortcuts/familia-hermes-android
# Then add the Termux:Widget on the home screen and tap "familia-hermes-android".
# If familia is already installed, a tap launches Hermes (skip full reinstall).
# No sudo. Does not sideload an APK (see packaging/android/README.md for the APK follow-up).
set -eu
PREFIX_DIR="${FAMILIA_PREFIX:-$HOME/familia}"
REPO="${PREFIX_DIR}/repo"
SCRIPT="$REPO/install/termux/install-hermes-android.sh"
if [ ! -f "$SCRIPT" ]; then
  # Fallback: this file lives at install/termux/widget/; sibling is install-hermes-android.sh
  HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
  SCRIPT="$HERE/../install-hermes-android.sh"
fi
[ -f "$SCRIPT" ] || {
  echo "familia-hermes-android: missing $SCRIPT (run the Termux installer first)" >&2
  exit 1
}
# Already installed? Launch only — do not re-run the full install.
if [ -x "$PREFIX_DIR/runtime/current/llama-server" ] \
   && { [ -x "${PREFIX:-/data/data/com.termux/files/usr}/bin/familia-start" ] \
        || [ -x "$PREFIX_DIR/bin/familia-start" ]; }; then
  exec sh "$SCRIPT" --launch-only --yes "$@"
fi
exec sh "$SCRIPT" "$@"
