#!/usr/bin/env bash
# familia-menu.sh: the familia menu. Every item shows the command it runs, so you
# learn the CLI as you go. The items come from one table, and the
# same table (scripts/menu-items.txt) drives --list, --run, the interactive menu
# and the Windows menu (familia.cmd).
#
# Usage:
#   ./familia-menu.sh                 interactive menu (needs a terminal)
#   ./familia-menu.sh --list          print every item with its key and command
#   ./familia-menu.sh --run KEY [ARG...]   run one item without the menu
#   ./familia-menu.sh --dry-run ...   show the command instead of running it
#   ./familia-menu.sh --yes ...       accept license review without a prompt (summary still shown)
#   ./familia-menu.sh --pipe          read menu choices from a pipe (for scripts and tests)
# Example:
#   ./familia-menu.sh --run skills.menu
# With no terminal (and no --list/--run/--pipe) it prints the items and exits 2.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}

ITEMS_FILE="$ROOT/scripts/menu-items.txt"
[ -f "$ITEMS_FILE" ] || { echo "familia-menu: $ITEMS_FILE is missing; restore it with: git checkout scripts/menu-items.txt" >&2; exit 1; }
ITEMS=$(grep -v '^#' "$ITEMS_FILE" | grep -v '^[[:space:]]*$' | awk -F'|' '$4 != ""')  # empty posix command = Windows only

DRY=0; PIPE=0; MODE=menu; RUN_KEY=""
say() { printf '%s\n' "$*"; }
err() { printf 'familia-menu: %s\n' "$*" >&2; }

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; }

installer() {
  case "${PREFIX:-}" in *com.termux*) echo install/termux/install.sh; return ;; esac
  echo install/linux/install.sh
}

expand() {  # PY/INSTALLER/PAGER placeholders -> real commands
  local c=$1
  c=${c//PY /$PY }
  c=${c//INSTALLER/$(installer)}
  c=${c//PAGER /${PAGER:-more} }
  printf '%s' "$c"
}

need_ok() {  # need_ok SPEC -> 0 if available
  local spec=$1 path text
  case "$spec" in
    "") return 0 ;;
    file:*) [ -e "${spec#file:}" ] ;;
    grep:*) path=${spec#grep:}; text=${path#*:}; path=${path%%:*}; [ -f "$path" ] && grep -q -- "$text" "$path" ;;
    *) return 1 ;;
  esac
}

shown() {  # command as displayed: {NAME:prompt} -> <name>
  local c
  c=$(expand "$1")
  printf '%s' "$c" | sed -E 's/\{([A-Z]+):[^}]*\}/<\1>/g'
}

field() { printf '%s\n' "$ITEMS" | awk -F'|' -v k="$1" -v f="$2" '$1==k {print $f; exit}'; }

groups() { printf '%s\n' "$ITEMS" | awk -F'|' '!seen[$2]++ {print $2}'; }

group_desc() {
  case "$1" in
    "Set up") echo "get the parts, settings, licenses, install" ;;
    "Skills") echo "pick the skills your agents use (green-zkillz)" ;;
    "Models") echo "add models, check the graph, see launch parameters" ;;
    "Agents (hermes)") echo "run hermes on one model or the whole graph" ;;
    "Self-improving harness (Harness2)") echo "opt-in; attach to any agent, review every change" ;;
    "Test & benchmark") echo "unit tests, offline plan, benchmark records" ;;
    "Hosts") echo "start servers, measure machines, phones" ;;
    "Advanced: models & graph") echo "model database, launch arguments, graph edits, scale-down" ;;
    "Advanced: agents") echo "skill folders, hermes self-test and escalation" ;;
    "Advanced: hosts & benchmarks") echo "benchmark records, power, CPU level, uninstall, FreeBSD" ;;
    "Help") echo "quick start, the full command list (docs/commands.md), what the menu leaves out" ;;
  esac
}

list_items() {
  local g
  say "familia menu items. Run one with: ./familia-menu.sh --run KEY [ARG...]"
  while IFS= read -r g; do
    say ""
    say "$g: $(group_desc "$g")"
    printf '%s\n' "$ITEMS" | while IFS='|' read -r key grp label cmd gate need wcmd; do
      [ "$grp" = "$g" ] || continue
      local note=""
      need_ok "$need" || note="  (not available yet)"
      [ "$gate" = lic ] && note="$note  (asks you to accept licenses first)"
      printf '  %-22s %s%s\n  %-22s   runs: %s\n' "$key" "$label" "$note" "" "$(shown "$cmd")"
    done
  done <<EOF2
$(groups)
EOF2
}

read_line() {  # read_line PROMPT VAR ; returns 1 on EOF
  local __p=$1 __v
  printf '%s' "$__p" >&2
  IFS= read -r __v || { [ -n "$__v" ] || return 1; }
  printf -v "$2" '%s' "$__v"
}

fill() {  # fill CMD ARGS... -> prints command with {NAME:prompt} replaced
  local cmd=$1; shift
  local out="" rest=$cmd ph name prompt def val
  while [[ $rest == *"{"*"}"* ]]; do
    out+=${rest%%\{*}; rest=${rest#*\{}; ph=${rest%%\}*}; rest=${rest#*\}}
    name=${ph%%:*}; prompt=${ph#*:}; def=""
    [[ $prompt =~ \[([^]]*)\] ]] && def=${BASH_REMATCH[1]}
    if [ $# -gt 0 ]; then val=$1; shift
    elif [ "$MODE" = run ]; then err "item needs $name ($prompt). Pass it after the key: --run KEY VALUE"; return 2
    else read_line "  $prompt: " val || return 1; fi
    [ -n "$val" ] || val=$def
    [ -n "$val" ] || { err "$name is required ($prompt)"; return 2; }
    out+=$(printf '%q' "$val")
  done
  printf '%s' "$out$rest"
}

run_item() {  # run_item KEY ARGS...
  local key=$1; shift
  local cmd gate need label
  label=$(field "$key" 3)
  [ -n "$label" ] || { err "no item '$key'. See: ./familia-menu.sh --list"; return 2; }
  cmd=$(field "$key" 4); gate=$(field "$key" 5); need=$(field "$key" 6)
  if ! need_ok "$need"; then
    err "'$label' is not available yet (needs ${need#*:}). It appears once that lands on main."
    return 1
  fi
  cmd=$(fill "$(expand "$cmd")" "$@") || return $?
  if [ "$DRY" = 1 ]; then
    [ "$gate" = lic ] && say "[dry-run] would first run: $PY scripts/licenses.py gate"
    say "[dry-run] $cmd"; return 0
  fi
  if [ "$gate" = lic ]; then
    $PY scripts/licenses.py gate || {
      local rc=$?
      err "stopped: the licenses for this selection are not accepted yet. Review them with: $PY scripts/licenses.py review"
      return $rc
    }
  fi
  say "Running: $cmd"
  bash -c "$cmd"
}

menu() {
  local gs g n choice items key
  while true; do
    say ""
    say "familia: what do you want to do?"
    gs=(); n=0
    while IFS= read -r g; do gs+=("$g"); n=$((n+1)); printf '  %d) %-36s %s\n' "$n" "$g" "$(group_desc "$g")"; done <<EOF2
$(groups)
EOF2
    say "  q) Quit"
    read_line "Choose 1-$n or q: " choice || { say ""; return 0; }
    case "$choice" in q|Q|quit|exit) return 0 ;; esac
    if ! [[ $choice =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "$n" ]; then
      say "'$choice' isn't one of the choices. Type a number from 1 to $n, or q."; continue
    fi
    g=${gs[$((choice-1))]}
    while true; do
      say ""; say "$g: $(group_desc "$g")"
      items=(); n=0
      while IFS='|' read -r key grp label cmd gate need wcmd; do
        [ "$grp" = "$g" ] || continue
        items+=("$key"); n=$((n+1))
        local note=""; need_ok "$need" || note=" (not available yet)"
        printf '  %d) %s%s\n       runs: %s\n' "$n" "$label" "$note" "$(shown "$cmd")"
      done <<EOF2
$ITEMS
EOF2
      say "  b) Back"
      read_line "Choose 1-$n or b: " choice || return 0
      case "$choice" in b|B|back|"") break ;; q|Q) return 0 ;; esac
      if ! [[ $choice =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "$n" ]; then
        say "'$choice' isn't one of the choices. Type a number from 1 to $n, or b."; continue
      fi
      run_item "${items[$((choice-1))]}" || say "(that step exited with status $?)"
      [ "$PIPE" = 1 ] || read_line "Press Enter to go back to the menu..." choice || return 0
    done
  done
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --list) MODE=list ;;
    --run) MODE=run; RUN_KEY=${2-}; shift || true; [ -n "$RUN_KEY" ] || { err "--run needs an item key (see --list)"; exit 2; }; shift; break ;;
    --run=*) MODE=run; RUN_KEY=${1#*=}; shift; break ;;
    --dry-run|-n) DRY=1 ;;
    --yes|-y) export FAMILIA_ACCEPT_LICENSES=yes ;;
    --pipe) PIPE=1; export FAMILIA_MENU_PIPE=1 ;;
    *) err "unknown option '$1'. Try: ./familia-menu.sh --help"; exit 2 ;;
  esac
  shift
done
# options may also follow --run KEY
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --yes|-y) export FAMILIA_ACCEPT_LICENSES=yes ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done

command -v "$PY" >/dev/null 2>&1 || { err "$PY was not found. Install Python 3 (Debian/Ubuntu: sudo apt install python3; Termux: pkg install python)."; exit 1; }

case "$MODE" in
  list) list_items; exit 0 ;;
  run) run_item "$RUN_KEY" ${ARGS[@]+"${ARGS[@]}"}; exit $? ;;
esac
if [ ! -t 0 ] && [ "$PIPE" != 1 ]; then
  list_items
  err "no terminal, so no interactive menu. Run an item with --run KEY, or pipe choices with --pipe."
  exit 2
fi
menu
