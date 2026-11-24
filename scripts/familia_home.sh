#!/bin/sh
# familia_home.sh: Talk to the protomodel is item 1. Find more models and
# Search my X / Twitter posts follow. The six areas stay equal to each other
# (Models, Harnesses, Agents, MCP servers, Tool sets, App store). Legacy menu
# is last. The legacy menu is also the fallback and the CLI for every action.
# Usage:
#   sh scripts/familia_home.sh                 interactive numbered menu
#   sh scripts/familia_home.sh --list-goals    print the numbered list and exit 0
#   sh scripts/familia_home.sh -l              same explicit list
# No tty (stdin is not a terminal, or FAMILIA_NO_TTY=1) opens the legacy
# numeric menu and reads stdin. It does not print the list and exit.
# CI=true alone does not do that: an interactive ssh with a tty stays here.
# Arrows and digits both select. gum is used only when it accepts numbers;
# otherwise this is the numeric prompt (arrows included). No gum at all falls
# back to the legacy menu.
#
# On a tty, Ctrl-C, Esc and EOF in a submenu return here. At this menu they
# exit 0. A running action still stays in the menu when interrupted.
# HUP and TERM leave, because the terminal is gone.
#
# gum is not installed unless you say yes. The default answer is no, and no
# falls back to the legacy menu. install-gum.sh verifies the pinned sha256.
set -eu
ROOT=$(unset CDPATH; cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
# Do not put ~/.local/bin first on PATH for every child. gum() looks there itself.
PY=${PYTHON:-python3}
gum() {
  if [ -n "${HOME:-}" ] && [ -x "${HOME}/.local/bin/gum" ]; then
    "${HOME}/.local/bin/gum" "$@"
    return $?
  fi
  command gum "$@"
}

_interrupted=0
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

Talk to the protomodel is 1. Then Find more models and Search my X / Twitter
posts. Then six equal items: Models, Harnesses, Agents, MCP servers, Tool sets,
App store. Each of those has install, list, start, stop and status.
Legacy menu is last. --list-goals prints the list and exits 0.
With no terminal, the legacy numeric menu reads stdin.
If gum is missing you are asked before any download (default no). No opens
the legacy menu:
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

# No tty means stdin is not a terminal, or FAMILIA_NO_TTY=1.
# Do not treat CI=true by itself as line mode.
no_stdin_tty() {
  if [ "${FAMILIA_NO_TTY:-}" = 1 ]; then
    return 0
  fi
  if [ -t 0 ]; then
    return 1
  fi
  return 0
}

if [ "$LIST_ONLY" = 1 ]; then
  print_goals
  exit 0
fi
if no_stdin_tty; then
  printf 'familia-home: no terminal; opening the legacy numeric menu.\n' >&2
  export FAMILIA_NO_TTY=1
  exec bash "$ROOT/familia-menu.sh" --pipe
fi

command -v "$PY" >/dev/null 2>&1 || fallback_legacy "$PY was not found"
"$PY" "$ROOT/scripts/home_catalog.py" --titles >/dev/null || fallback_legacy "the home catalog failed"

have_gum() {
  if [ -n "${HOME:-}" ] && [ -x "${HOME}/.local/bin/gum" ]; then
    return 0
  fi
  command -v gum >/dev/null 2>&1
}

gum_usable() {
  have_gum || return 1
  gum --version >/dev/null 2>&1 || return 1
  gum choose --help 2>&1 | grep -q -- '--header' || return 1
  gum choose --help 2>&1 | grep -q -- '--height' || return 1
}

# gum choose has no number keys unless a build advertises --numbered (#746).
gum_takes_numbers() {
  gum_usable || return 1
  gum choose --help 2>&1 | grep -q -- '--numbered'
}

# Ask before any download. install-gum.sh defaults to no and checks sha256.
if ! have_gum; then
  if [ "${FAMILIA_SKIP_GUM_INSTALL:-}" != 1 ] && [ -t 0 ] && [ -f "$ROOT/scripts/install-gum.sh" ]; then
    sh "$ROOT/scripts/install-gum.sh" || true
  fi
fi
if ! gum_usable; then
  if [ ! -t 0 ]; then
    printf 'familia-home: no terminal; opening the legacy numeric menu.\n' >&2
    export FAMILIA_NO_TTY=1
    exec bash "$ROOT/familia-menu.sh" --pipe
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

# 7-bit banner. Box drawing is not required; pipes and logs stay ASCII.
banner() {
  printf '%s\n' '  +------------------------------------------------------------------+'
  printf '%s\n' '  | familia   Talk first   six equal items   Legacy menu last        |'
  printf '%s\n' '  +------------------------------------------------------------------+'
}

# pick HEADER ITEM... sets PICKED.
# 0 chosen, 3 Esc, 4 EOF, 130 interrupt, 2 terminal could not be read.
# Digits and arrows both work. gum is used only when it accepts numbers.
pick() {
  _hdr=$1
  shift
  PICKED=
  note_interrupt
  printf '%s\n' "$_hdr" >&2
  _tmp=$(mktemp "${TMPDIR:-/tmp}/familia-home-pick.XXXXXX" 2>/dev/null) || return 2
  _rc=0
  if gum_takes_numbers; then
    set +e
    gum choose --numbered --header "$_hdr" --height 16 "$@" > "$_tmp"
    _rc=$?
    set -e
    if [ "$_rc" -eq 0 ]; then
      IFS= read -r PICKED < "$_tmp" || PICKED=
      rm -f "$_tmp" || true
      if [ -n "$PICKED" ]; then
        if [ -t 0 ]; then
          stty sane 2>/dev/null || true
        fi
        return 0
      fi
    fi
    # 1 is Esc from gum. 130 is Ctrl-C. Do not start a second prompt.
    if [ "$_rc" -eq 1 ] || [ "$_rc" -eq 130 ]; then
      rm -f "$_tmp" || true
      if [ -t 0 ]; then
        stty sane 2>/dev/null || true
      fi
      if [ "$_rc" -eq 1 ]; then
        return 3
      fi
      return 130
    fi
  fi
  set +e
  "$PY" "$ROOT/scripts/home_catalog.py" --select "$@" > "$_tmp"
  _rc=$?
  set -e
  if [ -t 0 ]; then
    stty sane 2>/dev/null || true
  fi
  if [ "$_rc" -eq 0 ]; then
    IFS= read -r PICKED < "$_tmp" || PICKED=
  fi
  rm -f "$_tmp" || true
  if [ "$_rc" -eq 0 ] && [ -n "$PICKED" ]; then
    return 0
  fi
  if [ "$_rc" -eq 0 ]; then
    return 1
  fi
  return "$_rc"
}

pick_home() {
  set --
  while IFS= read -r _item || [ -n "$_item" ]; do
    [ -n "$_item" ] || continue
    set -- "$@" "$_item"
  done <<EOF
$("$PY" "$ROOT/scripts/home_catalog.py" --items)
EOF
  pick "What do you want to do? Type a number or use arrows. q quits." "$@"
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
      case "$_area:$_verb" in
        models:install|models:start)
          printf 'Run %s %s now (--apply)? This can download models in the background. [y/N] ' "$_area" "$_verb" >&2
          ;;
        *)
          printf 'Run %s %s now (--apply)? [y/N] ' "$_area" "$_verb" >&2
          ;;
      esac
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
    if [ "$_area" = apps ]; then
      # App store extras: tweet cards (gum) and the static web page.
      _ok=0
      pick "$_title: install, list, start, stop, status. Quit leaves." \
        browse "web page" install list start stop status Back Quit || _ok=$?
    else
      _ok=0
      pick "$_title: install, list, start, stop, status. Quit leaves." \
        install list start stop status Back Quit || _ok=$?
    fi
    if [ "$_ok" != 0 ]; then
      # Esc, EOF and Ctrl-C in a submenu return to the main menu.
      case "$_ok" in
        3|4|130)
          _interrupted=0
          return 0
          ;;
        2)
          fallback_legacy "the numbered menu could not read the terminal"
          ;;
      esac
      printf 'familia-home: staying in %s. Choose Back or Quit.\n' "$_title" >&2
      continue
    fi
    _sel=$PICKED
    case "$_sel" in
      Quit) exit 0 ;;
      Back) return 0 ;;
      install|list|start|stop|status) run_verb "$_area" "$_sel" ;;
      browse)
        set +e; sh "$ROOT/scripts/appstore.sh"; set -e; note_interrupt ;;
      "web page")
        set +e; sh "$ROOT/scripts/appstore.sh" --html; set -e; note_interrupt ;;
      *) printf 'familia-home: unknown choice %s. Staying in the menu.\n' "$_sel" >&2 ;;
    esac
  done
}

# Restored from main (#548). q returns to this menu. Only exit 4 opens the UI.
legacy_goal() {
  case "$1" in
  "Open llama-ui web cockpit")
    # Switch screen first. q (exit 0) returns to this menu.
    # Item "Continue to web cockpit" (exit 4) is the only path to
    # open_ui.sh. Both stay children of this shell. Interrupt stays here.
    # No TTY: do not auto-open. Quit is the only exit.
    if [ -t 0 ] && [ -t 1 ]; then
      _st=0
      FAMILIA_COCKPIT_HOOK=1
      export FAMILIA_COCKPIT_HOOK
      sh "$ROOT/scripts/android-cockpit-switches.sh" || _st=$?
      if [ "$_st" -eq 4 ]; then
        sh "$ROOT/scripts/open_ui.sh" || true
      fi
    fi
    return 0
    ;;
  "List all models")
    "$PY" "$ROOT/scripts/catalog.py" models || true
    return 0
    ;;
  "Configure all graphs")
    "$PY" "$ROOT/scripts/catalog.py" graphs || true
    return 0
    ;;
  "Talk to the protomodel")
    sh "$ROOT/scripts/proto_chat.sh" || true
    return 0
    ;;
  "Find more models")
    sh "$ROOT/scripts/find_models.sh" || true
    return 0
    ;;
  "Search my X / Twitter posts")
    sh "$ROOT/scripts/search_x.sh" || true
    return 0
    ;;
  *)
    return 1
    ;;
  esac
}

home_note "Talk to the protomodel" || true
while true; do
  note_interrupt || true
  banner || true
  _ok=0
  pick_home || _ok=$?
  if [ "$_ok" != 0 ]; then
    # Esc, EOF and Ctrl-C at the main menu exit cleanly.
    case "$_ok" in
      3|4|130)
        _interrupted=0
        exit 0
        ;;
      2)
        fallback_legacy "the numbered menu could not read the terminal"
        ;;
    esac
    printf 'familia-home: staying in the menu. Choose Quit to leave.\n' >&2
    continue
  fi
  sel=$PICKED
  case "$sel" in
    Quit) exit 0 ;;
    "Talk to the protomodel"|"Find more models"|"Search my X / Twitter posts"|"Open llama-ui web cockpit"|"List all models"|"Configure all graphs")
      legacy_goal "$sel" || printf 'familia-home: staying in the menu.\n' >&2
      ;;
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
