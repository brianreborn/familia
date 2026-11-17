#!/bin/sh
# familia_home.sh: six equal top-level items. The legacy menu is the fallback
# and the CLI for every action (scripts/home_catalog.py via familia-menu.sh).
# Usage:
#   sh scripts/familia_home.sh                 interactive home
#   sh scripts/familia_home.sh --list-goals    print the six items (tests)
#   FAMILIA_NO_TTY=1 sh scripts/familia_home.sh
# List mode (no tty, FAMILIA_NO_TTY, or --list-goals) prints and exits 0.
# The interactive menu exits only when the choice is Quit.
# If gum is missing and scripts/install-gum.sh cannot install it, this execs
# the legacy menu instead of exiting.
set -eu
ROOT=$(unset CDPATH; cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PATH="${HOME:-}/.local/bin:${PATH:-}"
export PATH
PY=${PYTHON:-python3}

LIST_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --list-goals|-l) LIST_ONLY=1 ;;
    -h|--help)
      cat <<'USAGE'
Usage: sh scripts/familia_home.sh [--list-goals]

Six equal items: Models, Harnesses, Agents, MCP servers, Tool sets, App store.
Each has install, list, start, stop and status.
The menu exits only on Quit.
If gum cannot be installed, the legacy menu opens instead:
  ./familia menu | ./familia --legacy-menu | FAMILIA_LEGACY_MENU=1 ./familia
example: sh scripts/familia_home.sh --list-goals
USAGE
      exit 0 ;;
    *) printf 'familia-home: unknown arg %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

fallback_legacy() {
  printf 'familia-home: %s\n' "$1" >&2
  printf 'familia-home: falling back to the legacy menu. Type q to quit.\n' >&2
  exec bash "$ROOT/familia-menu.sh"
}

print_goals() {
  "$PY" "$ROOT/scripts/home_catalog.py" --list-home
}

if [ "$LIST_ONLY" = 1 ] || [ "${FAMILIA_NO_TTY:-}" = 1 ] || [ ! -t 0 ]; then
  print_goals
  exit 0
fi

command -v "$PY" >/dev/null 2>&1 || fallback_legacy "$PY was not found"
"$PY" "$ROOT/scripts/home_catalog.py" --titles >/dev/null || fallback_legacy "the home catalog failed"

have_gum() { command -v gum >/dev/null 2>&1; }

if ! have_gum; then
  if [ "${FAMILIA_SKIP_GUM_INSTALL:-}" != 1 ] && [ -f "$ROOT/scripts/install-gum.sh" ]; then
    sh "$ROOT/scripts/install-gum.sh" --yes || true
    PATH="${HOME:-}/.local/bin:${PATH:-}"
    export PATH
  fi
fi
if ! have_gum; then
  fallback_legacy "gum is not available and could not be installed"
fi

# Background first-try models. Failure does not leave the menu.
kick_prefetch() {
  [ -f "$ROOT/scripts/prefetch-first-models.sh" ] || return 0
  printf 'familia-home: PREFETCHING ORDNANCE in the background\n' >&2
  sh "$ROOT/scripts/prefetch-first-models.sh" --background >/dev/null 2>&1 || true
}

# scripts/osc7501.sh status. Skipped for pipes, logs, NO_COLOR, and dumb terminals.
home_note() {
  [ -t 1 ] || return 0
  [ -z "${NO_COLOR:-}" ] || return 0
  [ "${TERM:-dumb}" != dumb ] || return 0
  [ -f "$ROOT/scripts/osc7501.sh" ] || return 0
  # shellcheck disable=SC1091
  . "$ROOT/scripts/osc7501.sh"
  osc7501_emit working --id home --msg "$1" --title "familia home" --app familia 2>/dev/null || true
}

# 7-bit banner. Box drawing is not required; pipes and logs stay ASCII.
banner() {
  printf '%s\n' '  +------------------------------------------------------------------+'
  printf '%s\n' '  | familia   six equal items   Quit is the only exit               |'
  printf '%s\n' '  +------------------------------------------------------------------+'
}

# pick HEADER ITEM... -> prints the choice. Options are arguments so gum
# keeps the terminal on stdin. Returns 1 on cancel or EOF (not a quit).
pick() {
  _hdr=$1
  shift
  _sel=$(gum choose --header "$_hdr" --height 16 "$@") || return 1
  [ -n "$_sel" ] || return 1
  printf '%s\n' "$_sel"
}

area_of() {
  case "$1" in
    Models) printf '%s\n' models ;;
    Harnesses) printf '%s\n' harnesses ;;
    Agents) printf '%s\n' agents ;;
    "MCP servers") printf '%s\n' mcp ;;
    "Tool sets") printf '%s\n' tools ;;
    "App store") printf '%s\n' apps ;;
    *) return 1 ;;
  esac
}

run_verb() {
  _area=$1
  _verb=$2
  _apply=0
  case "$_verb" in
    install|start|stop)
      printf 'Run %s %s now (--apply)? [y/N] ' "$_area" "$_verb" >&2
      if ! IFS= read -r _ans; then
        printf 'familia-home: not confirmed. Staying in the menu.\n' >&2
        return 0
      fi
      case "$_ans" in
        y|Y|yes|YES) _apply=1 ;;
        *) printf 'familia-home: not confirmed. Staying in the menu.\n' >&2; return 0 ;;
      esac
      case "$_area:$_verb" in
        models:install|models:start) kick_prefetch ;;
      esac
      ;;
  esac
  set +e
  if [ "$_apply" = 1 ]; then
    "$PY" "$ROOT/scripts/home_catalog.py" "$_area" "$_verb" --apply
  else
    "$PY" "$ROOT/scripts/home_catalog.py" "$_area" "$_verb"
  fi
  _rc=$?
  set -e
  if [ "$_rc" != 0 ]; then
    printf 'familia-home: %s %s exited %s. Staying in the menu.\n' "$_area" "$_verb" "$_rc" >&2
  fi
  return 0
}

submenu() {
  _area=$1
  _title=$2
  while true; do
    if ! _sel=$(pick "$_title: install, list, start, stop, status. Quit leaves." \
      install list start stop status Back Quit); then
      printf 'familia-home: staying in %s. Choose Back or Quit.\n' "$_title" >&2
      continue
    fi
    case "$_sel" in
      Quit) exit 0 ;;
      Back) return 0 ;;
      install|list|start|stop|status) run_verb "$_area" "$_sel" ;;
      *) printf 'familia-home: unknown choice %s. Staying in the menu.\n' "$_sel" >&2 ;;
    esac
  done
}

home_note "six equal items"
while true; do
  banner
  if ! sel=$(pick "What do you want to do? Quit is the only exit." \
    Models Harnesses Agents "MCP servers" "Tool sets" "App store" "Legacy menu" Quit); then
    printf 'familia-home: staying in the menu. Choose Quit to leave.\n' >&2
    continue
  fi
  case "$sel" in
    Quit) exit 0 ;;
    "Legacy menu")
      set +e
      bash "$ROOT/familia-menu.sh"
      _rc=$?
      set -e
      if [ "$_rc" != 0 ]; then
        printf 'familia-home: legacy menu exited %s. Staying in the menu.\n' "$_rc" >&2
      fi
      ;;
    *)
      if ! area=$(area_of "$sel"); then
        printf 'familia-home: unknown choice %s. Staying in the menu.\n' "$sel" >&2
        continue
      fi
      submenu "$area" "$sel"
      ;;
  esac
done
