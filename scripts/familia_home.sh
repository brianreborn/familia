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
  printf 'familia-home: gum (Charm) is required for the new front door.\n' >&2
  printf 'Install:  go install github.com/charmbracelet/gum@latest\n' >&2
  printf '     or:  download a release from https://github.com/charmbracelet/gum/releases\n' >&2
  printf '     and put gum on PATH (this box: ~/.local/bin/gum).\n' >&2
  printf 'Legacy menu (no gum):  ./familia --legacy-menu\n' >&2
  exit 2
fi

gum style --border rounded --border-foreground 84 --foreground 159 --bold \
  --align center --width 64 --padding "0 2" \
  "familia" "Talk to the protomodel first — old menus are legacy"

CHOICE=$(printf '%s\n' "$GOALS" | gum choose --header "What do you want to do?" --height 10) || {
  printf 'familia-home: cancelled\n'
  exit 0
}

case "$CHOICE" in
  "Talk to the protomodel")
    exec sh "$ROOT/scripts/proto_chat.sh"
    ;;
  "Find more models")
    exec sh "$ROOT/scripts/find_models.sh"
    ;;
  "Search my X / Twitter posts")
    exec sh "$ROOT/scripts/search_x.sh"
    ;;
  "Install / first-time setup")
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
