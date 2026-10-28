#!/bin/sh
# familia_home.sh: Charm/gum front door. Old familia-menu.sh is legacy fallback only.
# Usage:
#   sh scripts/familia_home.sh              interactive gum launcher
#   sh scripts/familia_home.sh --list-goals  print the six goals (non-interactive / tests)
#   FAMILIA_NO_TTY=1 sh scripts/familia_home.sh   lists goals and exits 0
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
# Prefer user-local Charm gum (box installs land in ~/.local/bin).
PATH="${HOME:-}/.local/bin:${PATH:-}"
export PATH

LIST_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --list-goals|-l) LIST_ONLY=1 ;;
    -h|--help)
      cat <<'USAGE'
Usage: sh scripts/familia_home.sh [--list-goals]

Charm/gum goal launcher (default ./familia front door).
Requires gum on PATH for interactive use. Legacy catalog:
  ./familia menu | ./familia --legacy-menu | FAMILIA_LEGACY_MENU=1 ./familia
USAGE
      exit 0 ;;
    *) printf 'familia-home: unknown arg %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

GOALS="Talk to the protomodel
Find more models
Search my X / Twitter posts
Install / first-time setup
★ Required checks (must-run)
Legacy menu"

print_goals() {
  printf '%s\n' "familia home — goals (Charm/gum):"
  printf '%s\n' "$GOALS" | awk '{printf "  %d) %s\n", NR, $0}'
  printf 'Legacy fallback: ./familia --legacy-menu\n'
}

if [ "$LIST_ONLY" = 1 ] || [ "${FAMILIA_NO_TTY:-}" = 1 ] || [ ! -t 0 ]; then
  print_goals
  exit 0
fi

if ! command -v gum >/dev/null 2>&1; then
  if [ -f "$ROOT/scripts/osc7501.sh" ]; then
    # soft: blocked:auth-ish — gum missing
    # shellcheck disable=SC1091
    . "$ROOT/scripts/osc7501.sh"
    osc7501_emit blocked --id home --kind question --app familia \
      --msg "gum missing; install via scripts/install-gum.sh or use --legacy-menu" 2>/dev/null || true
  fi
  printf 'familia-home: gum (Charm) is required for the new front door.\n' >&2
  printf 'Install (user-local, no sudo):  sh scripts/install-gum.sh\n' >&2
  printf '     or re-run:                 sh install.sh --yes --no-start\n' >&2
  printf 'Legacy menu (no gum):  ./familia --legacy-menu\n' >&2
  exit 2
fi

# Pilot canopy — mecha HUD framing for the home.
if [ -f "$ROOT/scripts/pilot_hud.sh" ]; then
  # shellcheck disable=SC1091
  . "$ROOT/scripts/pilot_hud.sh"
  pilot_canopy "FAMILIA PILOT LINK"
else
  gum style --border double --border-foreground 51 --foreground 159 --bold \
    --align center --width 64 --padding "0 2" \
    "familia" "Talk to the protomodel first — old menus are legacy"
fi

CHOICE=$(printf '%s\n' "$GOALS" | gum choose --header "What do you want to do?" --height 10) || {
  printf 'familia-home: cancelled\n'
  exit 0
}

# Background ordnance prefetch when entering build/talk paths (UI-owned overlap).
kick_prefetch() {
  [ -f "$ROOT/scripts/prefetch-first-models.sh" ] || return 0
  if [ -f "$ROOT/scripts/pilot_hud.sh" ]; then
    pilot_strip "PREFETCHING ORDNANCE" "first-try models in background (.cache/prefetch-first-models.log)"
  else
    printf 'familia-home: prefetching first-try model in background…\n' >&2
  fi
  sh "$ROOT/scripts/prefetch-first-models.sh" --background >/dev/null 2>&1 || true
}

case "$CHOICE" in
  "Talk to the protomodel")
    kick_prefetch
    exec sh "$ROOT/scripts/proto_chat.sh"
    ;;
  "Find more models")
    exec sh "$ROOT/scripts/find_models.sh"
    ;;
  "Search my X / Twitter posts")
    exec sh "$ROOT/scripts/search_x.sh"
    ;;
  "Install / first-time setup")
    kick_prefetch
    exec sh "$ROOT/scripts/setup_goals.sh" first-time
    ;;
  "★ Required checks (must-run)")
    exec sh "$ROOT/scripts/required_checks.sh"
    ;;
  "Legacy menu")
    exec bash "$ROOT/familia-menu.sh"
    ;;
  *)
    printf 'familia-home: unknown choice %s\n' "$CHOICE" >&2
    exit 2
    ;;
esac
