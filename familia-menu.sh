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
#   ./familia-menu.sh --search TEXT   print every item matching TEXT (key, label, command, group)
#   ./familia-menu.sh --search TEXT --run N [ARG...]   run match number N
# In the menu, at any level: /word searches every group, ?word searches backward,
# n / N go to the next / previous match, and / alone repeats the last search.
# Examples:
#   ./familia-menu.sh --run skills.menu
#   ./familia-menu.sh --search hermes
# With no terminal (and no --list/--run/--search/--pipe) it prints the items and exits 2.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}

ITEMS_FILE="$ROOT/scripts/menu-items.txt"
[ -f "$ITEMS_FILE" ] || { echo "familia-menu: $ITEMS_FILE is missing; restore it with: git checkout scripts/menu-items.txt" >&2; exit 1; }
ITEMS=$(grep -v '^#' "$ITEMS_FILE" | grep -v '^[[:space:]]*$' | awk -F'|' '$4 != ""')  # empty posix command = Windows only

DRY=0; PIPE=0; MODE=menu; RUN_KEY=""; SEARCH=""
say() { printf '%s\n' "$*"; }
err() { printf '%s: %s\n' "${ERR_NAME:-familia-menu}" "$*" >&2; }

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; }

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
    "Help") echo "quick start, search, the full command list, what the menu leaves out" ;;
  esac
}

workflow_paths() {
  say "ACTIONABLE PATHS (prerequisites still apply; follow one goal at a time):"
  say "  New checkout: setup.licenses -> setup.configure -> setup.install (preview) ->"
  say "                setup.install-run -> hosts.start"
  say "  Existing graph node: models.check -> hosts.serve <NODE>"
  say "  Add a model: models.fetch-preview -> models.fetch -> add its node to graph.yaml ->"
  say "               models.check -> hosts.serve <NODE>"
  say "  Hermes: models.check -> agents.hermes (license-gated)"
  say "NOT DONE YET - FreeBSD llama.cpp 0.7.0 on angel: neither a FreeBSD build nor a"
  say "model-load smoke test has been run; angel is still unmeasured and cannot host graph nodes."
  say "After this checkout is available on angel, from code-bootstraps-llama.cpp:"
  say "  BUILD_DIR=build-freebsd GPU=off scripts/build-linux.sh"
  say "Then verify build-freebsd/bin/llama-server --version, measure angel, and re-check graph.yaml."
  say ""
}

list_items() {
  local g
  say "familia menu items. Run one with: ./familia-menu.sh --run KEY [ARG...]"
  workflow_paths
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

can_prompt() { [ -t 0 ] && [ "${FAMILIA_NO_TTY:-}" != 1 ]; }
short_hostname() { hostname 2>/dev/null | cut -d. -f1 | tr '[:upper:]' '[:lower:]'; }

fill() {  # fill CMD ARGS... -> CMD with {NAME:prompt} filled from ARGS (as the --flag before it, else in order); rest appended
  local cmd=$1; shift
  local args=("$@") out="" rest before ph i j n=0 val host_default
  local -a names=() prompts=() defs=() flags=() vals=() got=() pre=()
  rest=$cmd
  while [[ $rest == *"{"*"}"* ]]; do  # pass 1: placeholders, and the flag written just before each
    before=${rest%%\{*}; rest=${rest#*\{}; ph=${rest%%\}*}; rest=${rest#*\}}
    pre+=("$before"); names+=("${ph%%:*}"); prompts+=("${ph#*:}"); vals+=(""); got+=(0)
    if [[ ${ph#*:} =~ \[([^]]*)\] ]]; then defs+=("${BASH_REMATCH[1]}"); else defs+=(""); fi
    if [[ $before =~ (^|[[:space:]])(-[-A-Za-z0-9]+)[[:space:]]+$ ]]; then flags+=("${BASH_REMATCH[2]}"); else flags+=(""); fi
    n=$((n+1))
  done
  for ((j=0; j<n; j++)); do  # pass 2: --flag VALUE / --flag=VALUE given by the user
    [ -n "${flags[$j]}" ] && [ ${#args[@]} -gt 0 ] || continue
    for i in "${!args[@]}"; do
      if [ "${args[$i]}" = "${flags[$j]}" ] && [ $((i+1)) -lt ${#args[@]} ]; then
        vals[$j]=${args[$((i+1))]}; got[$j]=1; unset "args[$i]" "args[$((i+1))]"; break
      elif [[ ${args[$i]} == "${flags[$j]}="* ]]; then
        vals[$j]=${args[$i]#*=}; got[$j]=1; unset "args[$i]"; break
      fi
    done
    args=(${args[@]+"${args[@]}"})
  done
  for ((j=0; j<n; j++)); do  # pass 3: leading plain values in order, then defaults or prompts
    if [ "${defs[$j]}" = hostname ]; then
      host_default=$(short_hostname)
      defs[$j]=$host_default
      if [ -n "$host_default" ]; then
        prompts[$j]=${prompts[$j]//\[hostname\]/[$host_default]}
      else
        prompts[$j]=${prompts[$j]// \[hostname\]/}
      fi
    fi
    [ "${got[$j]}" = 1 ] && continue
    if [ ${#args[@]} -gt 0 ] && [[ ${args[0]} != -* ]]; then
      vals[$j]=${args[0]}; args=("${args[@]:1}")
    elif [ "$MODE" = menu ] || { [ -z "${defs[$j]}" ] && can_prompt; }; then
      read_line "  ${prompts[$j]}: " val || return 1; vals[$j]=$val
    elif [ -z "${defs[$j]}" ]; then
      err "item needs ${names[$j]} (${prompts[$j]}). Give it as a value: ${CLI_HINT:---run KEY} VALUE"; return 2
    fi
    [ -n "${vals[$j]}" ] || vals[$j]=${defs[$j]}
    [ -n "${vals[$j]}" ] || { err "${names[$j]} is required (${prompts[$j]})"; return 2; }
  done
  for ((j=0; j<n; j++)); do out+="${pre[$j]}$(printf '%q' "${vals[$j]}")"; done
  out+=$rest
  for val in ${args[@]+"${args[@]}"}; do out+=" $(printf '%q' "$val")"; done
  printf '%s' "$out"
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

# ---- search, like / ? n N in less and more ----------------------------------
LAST_SEARCH=""; SDIR=1; SCUR=0; SK=()
use_color() {
  case "${FAMILIA_COLOR:-auto}" in always) return 0 ;; never) return 1 ;; esac
  [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != dumb ]
}
# One awk pass does the matching and the highlighting, so a search stays fast on old machines.
AWK_LIB='
function shown(c,   out, m) {
  gsub(/PY /, py " ", c); gsub(/INSTALLER/, inst, c); gsub(/PAGER /, pager " ", c); out = ""
  while (match(c, /\{[A-Z]+:[^}]*\}/)) { m = substr(c, RSTART + 1, RLENGTH - 2); sub(/:.*/, "", m)
    out = out substr(c, 1, RSTART - 1) "<" m ">"; c = substr(c, RSTART + RLENGTH) }
  return out c
}
function hl(s,   out, i, ls) {
  if (!color || needle == "") return s
  out = ""
  while ((i = index(tolower(s), needle)) > 0) {
    out = out substr(s, 1, i - 1) "\033[7m" substr(s, i, length(needle)) "\033[0m"; s = substr(s, i + length(needle)) }
  return out s
}'
awk_items() {  # awk_items PROGRAM [awk -v args...]: runs PROGRAM over the table with the helpers above
  local prog=$1; shift
  printf '%s\n' "$ITEMS" | awk -F'|' -v py="$PY" -v inst="$(installer)" -v pager="${PAGER:-more}" "$@" "$AWK_LIB $prog"
}
find_matches() {  # find_matches TEXT -> SK=(keys), in table order, across every group
  local k
  SK=()
  while IFS= read -r k; do [ -n "$k" ] && SK+=("$k"); done <<EOF2
$(awk_items 'index(tolower($1 " " $2 " " $3 " " shown($4)), needle) { print $1 }' -v needle="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')")
EOF2
  return 0
}
show_match() {  # show_match N KEY NEEDLE MARK
  local note="" c=0
  need_ok "$(field "$2" 6)" || note=" (not available yet)"
  use_color && c=1
  awk_items '$1 == key {
      if ($5 == "lic") note = note " (asks you to accept licenses first)"
      printf "%s%2d) %s > %s%s\n       key: %s   runs: %s\n", mark, n, hl($2), hl($3), note, hl($1), hl(shown($4)) }' \
    -v key="$2" -v n="$1" -v mark="$4" -v note="$note" -v color="$c" \
    -v needle="$(printf '%s' "$3" | tr '[:upper:]' '[:lower:]')"
}
no_match() { say "No item matches '$1'. Try a shorter word, or a word from a command (e.g. /hermes, /dry-run)."; }
print_matches() {  # print_matches TEXT ; returns 1 when nothing matches
  local t=$1 i
  find_matches "$t"
  [ ${#SK[@]} -gt 0 ] || { no_match "$t"; return 1; }
  say "${#SK[@]} item(s) match '$t':"
  for i in "${!SK[@]}"; do show_match $((i+1)) "${SK[$i]}" "$t" "  "; done
}
search_ui() {  # search_ui OP TEXT ; OP is / ? n N. Returns 3 to quit the menu.
  local op=$1 t=$2 choice k i
  case "$op" in
    /|\?)
      [ -n "$t" ] || t=$LAST_SEARCH
      [ -n "$t" ] || { say "No previous search. Type / and a word, e.g. /model"; return 0; }
      LAST_SEARCH=$t; [ "$op" = / ] && SDIR=1 || SDIR=-1
      find_matches "$t"
      [ ${#SK[@]} -gt 0 ] || { no_match "$t"; return 0; }
      [ "$SDIR" = 1 ] && SCUR=0 || SCUR=$(( ${#SK[@]} - 1 ))
      say ""; say "Search: '$t' (${#SK[@]} match(es) in every group; > marks the current one)"
      for i in "${!SK[@]}"; do
        if [ "$i" = "$SCUR" ]; then k="> "; else k="  "; fi
        show_match $((i+1)) "${SK[$i]}" "$t" "$k"
      done ;;
    n|N)
      t=$LAST_SEARCH
      [ -n "$t" ] || { say "No previous search. Type / and a word, e.g. /model"; return 0; }
      [ ${#SK[@]} -gt 0 ] || find_matches "$t"
      [ ${#SK[@]} -gt 0 ] || { no_match "$t"; return 0; }
      if [ "$op" = n ]; then SCUR=$(( (SCUR + SDIR + ${#SK[@]}) % ${#SK[@]} ))
      else SCUR=$(( (SCUR - SDIR + ${#SK[@]}) % ${#SK[@]} )); fi
      say "match $((SCUR+1)) of ${#SK[@]} for '$t':"
      show_match $((SCUR+1)) "${SK[$SCUR]}" "$t" "> " ;;
  esac
  while true; do
    read_line "Choose 1-${#SK[@]} to run, n/N next/previous match, /word to search again, b back: " choice || return 3
    case "$choice" in
      b|B|back|"") return 0 ;;
      q|Q) return 3 ;;
      n|N) search_ui "$choice" ""; return $? ;;
      /*|\?*) search_ui "${choice:0:1}" "${choice:1}"; return $? ;;
    esac
    if ! [[ $choice =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#SK[@]} ]; then
      say "'$choice' isn't one of the choices. Type a number from 1 to ${#SK[@]}, n, N, /word or b."; continue
    fi
    SCUR=$((choice-1))
    run_item "${SK[$SCUR]}" || say "(that step exited with status $?)"
    [ "$PIPE" = 1 ] || read_line "Press Enter to go back to the menu..." choice || return 3
    return 0
  done
}
search_key() {  # handle /x ?x n N typed at any menu prompt; returns 0 handled (stay), 3 quit, 1 not a search
  case "$1" in
    /*|\?*) search_ui "${1:0:1}" "${1:1}" || return $? ;;
    n|N) search_ui "$1" "" || return $? ;;
    *) return 1 ;;
  esac
  return 0
}

menu() {
  local gs g n choice items key first=1
  while true; do
    say ""
    if [ "$first" = 1 ]; then workflow_paths; first=0; fi
    say "familia: what do you want to do?"
    gs=(); n=0
    while IFS= read -r g; do gs+=("$g"); n=$((n+1)); printf '  %2d) %-36s %s\n' "$n" "$g" "$(group_desc "$g")"; done <<EOF2
$(groups)
EOF2
    say "  q) Quit      /word search every group (n/N next/previous match)"
    read_line "Choose 1-$n, /search or q: " choice || { say ""; return 0; }
    case "$choice" in q|Q|quit|exit) return 0 ;; esac
    local rc=0; search_key "$choice" || rc=$?
    case $rc in 0) continue ;; 3) return 0 ;; esac
    if ! [[ $choice =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "$n" ]; then
      say "'$choice' isn't one of the choices. Type a number from 1 to $n, /word to search, or q."; continue
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
      say "  b) Back      /word search every group (n/N next/previous match)"
      read_line "Choose 1-$n, /search or b: " choice || return 0
      case "$choice" in b|B|back|"") break ;; q|Q) return 0 ;; esac
      local rc=0; search_key "$choice" || rc=$?
      case $rc in 0) continue ;; 3) return 0 ;; esac
      if ! [[ $choice =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "$n" ]; then
        say "'$choice' isn't one of the choices. Type a number from 1 to $n, /word to search, or b."; continue
      fi
      run_item "${items[$((choice-1))]}" || say "(that step exited with status $?)"
      [ "$PIPE" = 1 ] || read_line "Press Enter to go back to the menu..." choice || return 0
    done
  done
}

# ---- familia(1): `familia COMMAND ...` (names in scripts/cli-commands.txt, engine scripts/familia_cli.py) ----
script_part() {  # the command up to and including its script, for `familia COMMAND --help`
  local c=$1 out="" t
  for t in $c; do
    out+="${out:+ }$t"
    case "$t" in *.py|*.sh|*.ps1|familia-monitor|with-fleet.sh) [ -f "$t" ] && { printf '%s' "$out"; return 0; } ;; esac
  done
  return 1
}
run_raw() {  # run_raw GATE CMD ARGS...
  local gate=$1 cmd=$2 a; shift 2
  cmd=$(expand "$cmd")
  for a in "$@"; do cmd+=" $(printf '%q' "$a")"; done
  if [ "$DRY" = 1 ]; then
    [ "$gate" = lic ] && say "[dry-run] would first run: $PY scripts/licenses.py gate"
    say "[dry-run] ${cmd% }"; return 0
  fi
  if [ "$gate" = lic ]; then
    $PY scripts/licenses.py gate || { local rc=$?; err "stopped: the licenses for this selection are not accepted yet. Review them with: $PY scripts/licenses.py review"; return $rc; }
  fi
  bash -c "$cmd"
}
cli_help() {  # cli_help [--man | COMMAND...]
  if [ "${1:-}" = --man ]; then
    if command -v man >/dev/null 2>&1; then man "$ROOT/man/familia.1"; return $?; fi
    err "man is not installed here; showing the plain help instead (the page is man/familia.1)."
    $PY scripts/familia_cli.py help; return $?
  fi
  $PY scripts/familia_cli.py help "$@"
}
cli_search() {  # cli_search WORD [--run N ARG...]
  [ $# -ge 1 ] && [ -n "$1" ] || { err "search needs a word, e.g. familia search model"; return 2; }
  SEARCH=$1; shift
  if [ "${1:-}" = --run ]; then
    [ $# -ge 2 ] || { err "--run needs a match number"; return 2; }
    find_matches "$SEARCH"
    [ ${#SK[@]} -gt 0 ] || { no_match "$SEARCH" >&2; return 1; }
    local n=$2; shift 2
    if [[ $n =~ ^[0-9]+$ ]]; then
      [ "$n" -ge 1 ] && [ "$n" -le ${#SK[@]} ] || { err "--run $n: there are ${#SK[@]} match(es) for '$SEARCH'"; return 2; }
      n=${SK[$((n-1))]}
    fi
    MODE=run; run_item "$n" "$@"; return $?
  fi
  local rc=0; print_matches "$SEARCH" || rc=$?
  [ $rc = 0 ] && say "Run one with: familia search $(printf '%q' "$SEARCH") --run N [VALUE...]"
  return $rc
}
cli_main() {
  while [ $# -gt 0 ]; do  # options before the command belong to familia itself
    case "$1" in
      --dry-run|-n) DRY=1 ;;
      --yes|-y) export FAMILIA_ACCEPT_LICENSES=yes ;;
      --pipe) PIPE=1; export FAMILIA_MENU_PIPE=1 ;;
      -h|--help) shift; cli_help "$@"; return $? ;;
      --list) list_items; return 0 ;;
      --run) shift; [ $# -ge 1 ] || { err "--run needs an item key (see: familia list)"; return 2; }
             MODE=run; local k=$1; shift; run_item "$k" "$@"; return $? ;;
      --search) shift; cli_search "$@"; return $? ;;
      --search=*) local w=${1#*=}; shift; cli_search "$w" "$@"; return $? ;;
      -*) err "unknown option '$1'. Try: familia help"; return 2 ;;
      *) break ;;
    esac
    shift
  done
  [ $# -gt 0 ] || { MODE=menu; start_menu; return $?; }
  case "$1" in
    help) shift; cli_help "$@"; return $? ;;
    list) list_items; return 0 ;;
    run) shift; [ $# -ge 1 ] || { err "run needs an item key (see: familia list)"; return 2; }
         MODE=run; local k=$1; shift; run_item "$k" "$@"; return $? ;;
    search) shift; cli_search "$@"; return $? ;;
    menu) MODE=menu; start_menu; return $? ;;
    completion) shift; $PY scripts/familia_cli.py completion "$@"; return $? ;;
  esac
  local kind f1 f2 f3 res
  res=$($PY scripts/familia_cli.py resolve "$@") || return 2
  read -r kind f1 f2 f3 <<<"$res"
  case "$kind" in
    item) local words=("${@:1:$f2}"); shift "$f2"; CLI_HINT="familia ${words[*]}"
          if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then cli_help_item "$f1" "${words[@]}"; return $?; fi
          MODE=run; run_item "$f1" "$@"; return $? ;;
    raw) shift "$f1"
         if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then bash -c "$(expand "$f3") --help"; return $?; fi
         [ "$f2" = - ] && f2=""
         run_raw "$f2" "$f3" "$@"; return $? ;;
    *) err "unknown command '$1'. Try: familia help, or: familia search $1"; return 2 ;;
  esac
}
cli_help_item() {  # cli_help_item KEY WORDS...: familia's view of the item, then the script's own --help
  local key=$1 sp; shift
  $PY scripts/familia_cli.py help "$@"
  sp=$(script_part "$(expand "$(field "$key" 4)")") || return 0
  say ""; say "--- $sp --help ---"
  bash -c "$sp --help"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --list) MODE=list ;;
    --cli) MODE=cli; shift; break ;;
    --run) MODE=run; RUN_KEY=${2-}; shift || true; [ -n "$RUN_KEY" ] || { err "--run needs an item key (see --list)"; exit 2; }; shift; break ;;
    --run=*) MODE=run; RUN_KEY=${1#*=}; shift; break ;;
    --dry-run|-n) DRY=1 ;;
    --yes|-y) export FAMILIA_ACCEPT_LICENSES=yes ;;
    --pipe) PIPE=1; export FAMILIA_MENU_PIPE=1 ;;
    --search) [ $# -ge 2 ] && [ -n "$2" ] || { err "--search needs a word, e.g. --search model"; exit 2; }
              SEARCH=$2; [ "$MODE" = menu ] && MODE=search; shift ;;
    --search=*) SEARCH=${1#*=}; [ "$MODE" = menu ] && MODE=search ;;
    *) err "unknown option '$1'. Try: ./familia-menu.sh --help"; exit 2 ;;
  esac
  shift
done
start_menu() {
  if [ ! -t 0 ] && [ "$PIPE" != 1 ]; then
    list_items
    err "no terminal, so no interactive menu. Run an item with --run KEY, or pipe choices with --pipe."
    return 2
  fi
  menu
}
if [ "$MODE" = cli ]; then
  ERR_NAME=familia
  command -v "$PY" >/dev/null 2>&1 || { err "$PY was not found. Install Python 3 (Debian/Ubuntu: sudo apt install python3; Termux: pkg install python)."; exit 1; }
  rc=0; cli_main "$@" || rc=$?; exit $rc
fi
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

if [ -n "$SEARCH" ] && [ "$MODE" = run ]; then  # --search TEXT --run N: N is a match number
  find_matches "$SEARCH"
  [ ${#SK[@]} -gt 0 ] || { no_match "$SEARCH" >&2; exit 1; }
  if [[ $RUN_KEY =~ ^[0-9]+$ ]]; then
    [ "$RUN_KEY" -ge 1 ] && [ "$RUN_KEY" -le ${#SK[@]} ] || { err "--run $RUN_KEY: there are ${#SK[@]} match(es) for '$SEARCH'"; exit 2; }
    RUN_KEY=${SK[$((RUN_KEY-1))]}
  fi
fi
case "$MODE" in
  list) list_items; exit 0 ;;
  search) rc=0; print_matches "$SEARCH" || rc=$?
          [ $rc = 0 ] && say "Run one with: ./familia-menu.sh --search $(printf '%q' "$SEARCH") --run N [ARG...]"; exit $rc ;;
  run) run_item "$RUN_KEY" ${ARGS[@]+"${ARGS[@]}"}; exit $? ;;
esac
if [ ! -t 0 ] && [ "$PIPE" != 1 ]; then
  list_items
  err "no terminal, so no interactive menu. Run an item with --run KEY, or pipe choices with --pipe."
  exit 2
fi
menu
