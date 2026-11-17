#!/bin/sh
# familia_home.sh: six equal top-level items. The legacy menu is the fallback
# and the CLI for every action (scripts/home_catalog.py via familia-menu.sh).
# Usage:
#   sh scripts/familia_home.sh                 interactive home
#   sh scripts/familia_home.sh --list-goals    print the six items (tests)
#   FAMILIA_NO_TTY=1 sh scripts/familia_home.sh
# List mode (no tty, FAMILIA_NO_TTY, or --list-goals) prints and exits 0.
# The interactive menu exits only on Quit.
#
# Ctrl-C (INT) stays in the menu. HUP and TERM leave, because the terminal is gone.
# An ignored INT is not used: a child action must still be interruptible.
# gum exit 1 or 130 after 0.2s is a cancel. Anything else, or a cancel faster
# than 0.2s, counts as a failure. After 3 failures the legacy menu opens.
# If stdin is not a terminal at that point, exit 2 (closed input, not a quit).
# FAMILIA_HOME_FORCE_MENU=1 enters the loop even when stdin is not a terminal.
#
# gum is not installed unless you say yes. The default answer is no, and no
# falls back to the legacy menu. install-gum.sh verifies the pinned sha256.
set -eu
ROOT=$(unset CDPATH; cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
# Tests set HOME to an empty directory so a real ~/.local/bin/gum cannot shadow a stub.
PATH="${HOME:-}/.local/bin:${PATH:-}"
export PATH
PY=${PYTHON:-python3}

_interrupted=0
GUM_FAILS=0
on_int() {
  _interrupted=1
  printf '\n' >&2
  if [ -t 0 ]; then
    stty sane 2>/dev/null || true
  fi
}
trap on_int INT
trap 'printf "familia-home: terminal closed\n" >&2; exit 129' HUP
trap 'printf "familia-home: stopped\n" >&2; exit 143' TERM

LIST_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --list-goals|-l) LIST_ONLY=1 ;;
    -h|--help)
      cat <<'USAGE'
Usage: sh scripts/familia_home.sh [--list-goals]

Six equal items: Models, Harnesses, Agents, MCP servers, Tool sets, App store.
Each has install, list, start, stop and status.
The menu exits only on Quit. Ctrl-C stays in the menu.
If gum is missing you are asked before any download (default no). No, or a gum
that keeps failing, opens the legacy menu:
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

note_interrupt() {
  if [ "$_interrupted" = 1 ]; then
    _interrupted=0
    printf 'familia-home: interrupted; staying in the menu. Choose Quit to leave.\n' >&2
  fi
}

print_goals() {
  "$PY" "$ROOT/scripts/home_catalog.py" --list-home
}

if [ "${FAMILIA_HOME_FORCE_MENU:-}" != 1 ]; then
  if [ "$LIST_ONLY" = 1 ] || [ "${FAMILIA_NO_TTY:-}" = 1 ] || [ ! -t 0 ]; then
    print_goals
    exit 0
  fi
fi

command -v "$PY" >/dev/null 2>&1 || fallback_legacy "$PY was not found"
"$PY" "$ROOT/scripts/home_catalog.py" --titles >/dev/null || fallback_legacy "the home catalog failed"

have_gum() { command -v gum >/dev/null 2>&1; }

gum_usable() {
  have_gum || return 1
  gum --version >/dev/null 2>&1 || return 1
  gum choose --help 2>&1 | grep -q -- '--header' || return 1
  gum choose --help 2>&1 | grep -q -- '--height' || return 1
}

# Ask before any download. install-gum.sh defaults to no and checks sha256.
if ! have_gum; then
  if [ "${FAMILIA_SKIP_GUM_INSTALL:-}" != 1 ] && [ -t 0 ] && [ -f "$ROOT/scripts/install-gum.sh" ]; then
    sh "$ROOT/scripts/install-gum.sh" || true
    PATH="${HOME:-}/.local/bin:${PATH:-}"
    export PATH
  fi
fi
if ! gum_usable; then
  if [ ! -t 0 ]; then
    printf 'familia-home: gum is not usable and stdin is not a terminal. Not a quit.\n' >&2
    exit 2
  fi
  fallback_legacy "gum is missing, too old, or failed its version check"
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

now_ms() { "$PY" -c 'import time; print(int(time.monotonic()*1000))'; }

# 7-bit banner. Box drawing is not required; pipes and logs stay ASCII.
banner() {
  printf '%s\n' '  +------------------------------------------------------------------+'
  printf '%s\n' '  | familia   six equal items   Quit is the only exit               |'
  printf '%s\n' '  +------------------------------------------------------------------+'
}

gum_failed() {
  GUM_FAILS=$((GUM_FAILS + 1))
  if [ "$GUM_FAILS" -ge 3 ]; then
    if [ ! -t 0 ]; then
      printf 'familia-home: input closed. Not a quit.\n' >&2
      exit 2
    fi
    fallback_legacy "gum failed ${GUM_FAILS} times"
  fi
  sleep 1 || true
  printf 'familia-home: %s; retry %s of 3\n' "$1" "$GUM_FAILS" >&2
  return 1
}

# pick HEADER ITEM... sets PICKED. Returns 1 on cancel (not a quit).
# Not called in a command substitution: GUM_FAILS has to survive the call.
pick() {
  _hdr=$1
  shift
  PICKED=
  note_interrupt
  if ! gum_usable; then
    gum_failed "gum is not usable"
    return 1
  fi
  _t0=$(now_ms)
  _tmp=$(mktemp "${TMPDIR:-/tmp}/familia-home-pick.XXXXXX")
  set +e
  gum choose --header "$_hdr" --height 16 "$@" > "$_tmp"
  _rc=$?
  set -e
  _t1=$(now_ms)
  _sel=$(cat "$_tmp" 2>/dev/null || true)
  rm -f "$_tmp"
  _dt=$((_t1 - _t0))
  if [ "$_rc" -eq 0 ] && [ -n "${_sel:-}" ]; then
    GUM_FAILS=0
    PICKED=$_sel
    return 0
  fi
  # exit 1 is Esc. exit 130 is Ctrl-C while gum owns the terminal.
  if { [ "$_rc" -eq 1 ] || [ "$_rc" -eq 130 ]; } && [ "$_dt" -ge 200 ]; then
    GUM_FAILS=0
    return 1
  fi
  gum_failed "gum exited ${_rc}"
  return 1
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

read_required() {
  _prompt=$1
  printf '%s' "$_prompt" >&2
  if ! IFS= read -r _got; then
    note_interrupt
    printf 'familia-home: not confirmed. Staying in the menu.\n' >&2
    return 1
  fi
  if [ -z "$_got" ]; then
    printf 'familia-home: not confirmed. Staying in the menu.\n' >&2
    return 1
  fi
  printf '%s\n' "$_got"
}

run_verb() {
  _area=$1
  _verb=$2
  _apply=0
  _arg=
  case "$_verb" in
    install|start|stop)
      printf 'Run %s %s now (--apply)? [y/N] ' "$_area" "$_verb" >&2
      if ! IFS= read -r _ans; then
        note_interrupt
        printf 'familia-home: not confirmed. Staying in the menu.\n' >&2
        return 0
      fi
      case "$_ans" in
        y|Y|yes|YES) _apply=1 ;;
        *) printf 'familia-home: not confirmed. Staying in the menu.\n' >&2; return 0 ;;
      esac
      case "$_area:$_verb" in
        models:install)
          _arg=$(read_required 'Hugging Face repo ORG/NAME (empty cancels): ') || return 0
          ;;
        harnesses:start|harnesses:stop)
          _arg=$(read_required 'Agent name (empty cancels): ') || return 0
          ;;
        tools:install)
          _arg=$(read_required 'Skill id (empty cancels): ') || return 0
          ;;
      esac
      case "$_area:$_verb" in
        models:install|models:start) kick_prefetch ;;
      esac
      ;;
  esac
  set +e
  if [ "$_apply" = 1 ]; then
    if [ -n "$_arg" ]; then
      "$PY" "$ROOT/scripts/home_catalog.py" "$_area" "$_verb" --apply "$_arg"
    else
      "$PY" "$ROOT/scripts/home_catalog.py" "$_area" "$_verb" --apply
    fi
  else
    "$PY" "$ROOT/scripts/home_catalog.py" "$_area" "$_verb"
  fi
  _rc=$?
  set -e
  note_interrupt
  if [ "$_rc" != 0 ]; then
    printf 'familia-home: %s %s exited %s. Staying in the menu.\n' "$_area" "$_verb" "$_rc" >&2
  fi
  return 0
}

submenu() {
  _area=$1
  _title=$2
  while true; do
    note_interrupt
    if ! pick "$_title: install, list, start, stop, status. Quit leaves." \
      install list start stop status Back Quit; then
      printf 'familia-home: staying in %s. Choose Back or Quit.\n' "$_title" >&2
      continue
    fi
    _sel=$PICKED
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
  note_interrupt
  banner
  if ! pick "What do you want to do? Quit is the only exit." \
    Models Harnesses Agents "MCP servers" "Tool sets" "App store" "Legacy menu" Quit; then
    printf 'familia-home: staying in the menu. Choose Quit to leave.\n' >&2
    continue
  fi
  sel=$PICKED
  case "$sel" in
    Quit) exit 0 ;;
    "Legacy menu")
      set +e
      bash "$ROOT/familia-menu.sh"
      _rc=$?
      set -e
      note_interrupt
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
