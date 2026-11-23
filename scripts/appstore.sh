#!/bin/sh
# appstore.sh: gum view of the app store (tweets that promote apps).
# Usage:
#   sh scripts/appstore.sh            interactive (gum: banner, platform filter, cards, open a link)
#   sh scripts/appstore.sh --print    plain text cards, no prompts (also used without gum or a TTY)
#   sh scripts/appstore.sh --platform Android --print
#   sh scripts/appstore.sh --html     write the HTML page and print its path
#   sh scripts/appstore.sh --gum-print  gum-styled cards to stdout, no prompts (needs gum)
# Data: scripts/appstore.py (release appstore/data first, then the example fixture).
# No network, no listener. Opening a link only runs your desktop opener after you pick it.
set -eu
ROOT=$(unset CDPATH; cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}
APP="$ROOT/scripts/appstore.py"
gum() {
  if [ -n "${HOME:-}" ] && [ -x "${HOME}/.local/bin/gum" ]; then
    "${HOME}/.local/bin/gum" "$@"
    return $?
  fi
  command gum "$@"
}
have_gum() {
  { [ -n "${HOME:-}" ] && [ -x "${HOME}/.local/bin/gum" ]; } || command -v gum >/dev/null 2>&1
}

PRINT=0
PLATFORM=All
HTML=0
GUMPRINT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --print|-p) PRINT=1 ;;
    --html) HTML=1 ;;
    --gum-print) GUMPRINT=1 ;;
    --platform) PLATFORM=${2:-All}; shift ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'appstore: unknown arg %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$HTML" = 1 ]; then
  exec "$PY" "$APP" html --platform "$PLATFORM"
fi

interactive=1
if [ "$PRINT" = 1 ] || [ "${FAMILIA_NO_TTY:-}" = 1 ] || ! [ -t 0 ] || ! [ -t 1 ] || ! have_gum; then
  interactive=0
fi

# gum cards: app first (amber border), tweet below. One gum style per card.
gum_cards() {
  gum style --border double --border-foreground 51 --foreground 159 --bold \
    --align center --width 72 --padding "0 1" \
    "$("$PY" "$APP" banner)" "" "apps people are tweeting about"
  _src=$("$PY" "$APP" where | cut -f1)
  _n=$("$PY" "$APP" links --platform "$1" | wc -l | tr -d ' ')
  gum style --foreground 245 "  source: $_src  |  platform: $1  |  $_n apps"
  _i=0
  while [ "$_i" -lt "$_n" ]; do
    "$PY" "$APP" card "$_i" --platform "$1" --width 72 \
      | gum style --border rounded --border-foreground 214 --foreground 230 \
          --width 72 --padding "0 1"
    _i=$((_i + 1))
  done
}

open_link() {
  _url=$1
  case "$_url" in http://*|https://*) ;; *) printf 'appstore: not opening %s\n' "$_url" >&2; return 0 ;; esac
  if command -v termux-open-url >/dev/null 2>&1; then termux-open-url "$_url" || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$_url" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then open "$_url" || true
  else printf '%s\n' "$_url"
  fi
}

if [ "$GUMPRINT" = 1 ]; then
  have_gum || { printf 'appstore: gum not found; use --print\n' >&2; exit 1; }
  gum_cards "$PLATFORM"
  exit 0
fi

if [ "$interactive" = 0 ]; then
  exec "$PY" "$APP" text --platform "$PLATFORM"
fi

while true; do
  _plats=$("$PY" "$APP" platforms) || exit 1
  # shellcheck disable=SC2086
  _p=$(printf 'All\n%s\nWeb page (HTML)\nQuit\n' "$_plats" | gum choose --header "App store: pick a platform" --height 12) || exit 0
  case "$_p" in
    Quit|"") exit 0 ;;
    "Web page (HTML)")
      _page=$("$PY" "$APP" html) && { printf 'wrote %s\n' "$_page"; open_link "file://$_page" 2>/dev/null || true; }
      continue ;;
  esac
  gum_cards "$_p" | gum pager --soft-wrap=false || true
  _pick=$("$PY" "$APP" links --platform "$_p" | cut -f1 | { cat; printf 'Back\n'; } | gum filter --placeholder "open which app's link? (Back returns)") || continue
  [ "$_pick" = Back ] && continue
  _url=$("$PY" "$APP" links --platform "$_p" | awk -F '\t' -v n="$_pick" '$1 == n { print $3; exit }')
  [ -n "$_url" ] && open_link "$_url"
done
