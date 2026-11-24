#!/usr/bin/env bash
# scripts/menu-keys.sh: arrow keys for familia-menu.sh (epic #733 M1). Sourced, not run.
# Usage (from familia-menu.sh's nav_read):  menu_key_read PROMPT VAR COUNT
#   Reads one answer on a terminal with scripts/menu_keys.py and sets VAR to the
#   text a typed line would give: the highlighted number on Enter (Up/Down wrap,
#   Home/End), b for Esc or Backspace on an empty line, < / > for PgUp / PgDn,
#   q at once, and anything typed (digits, h, /word, &word, FOO=1 N ARG) on Enter.
#   Returns 1 at end of input (Ctrl-D), like read_line. Ctrl-C restores the
#   terminal and stops the menu (exit 130).
#   Falls back to read_line when the picker cannot use the terminal (M2's probe says
#   legacy), stdout or stderr is not a terminal, or FAMILIA_MENU_ARROWS=0.
# Sourcing only defines menu_key_read (no stty, no raw mode). Example:
#   . scripts/menu-keys.sh; menu_key_read "Choose 1-3: " choice 3
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi
menu_key_read() {  # menu_key_read PROMPT VAR COUNT ; returns 1 on EOF
  local __mk_p=$1 __mk_var=$2 __mk_n=${3:-0} __mk_out __mk_rc=0
  if [ "${FAMILIA_MENU_ARROWS:-1}" = 0 ] || [ "${MENU_KEYS_BROKEN:-0}" = 1 ] || [ "${FAMILIA_NO_TTY:-}" = 1 ] || ! [ -t 1 ] || ! [ -t 2 ]; then
    read_line "$__mk_p" "$__mk_var"; return
  fi
  __mk_out=$("${PY:-python3}" "${ROOT:-.}/scripts/menu_keys.py" pick --prompt "$__mk_p" --count "$__mk_n" --prev --next) || __mk_rc=$?
  case $__mk_rc in
    0) printf -v "$__mk_var" '%s' "$__mk_out"; return 0 ;;
    4) return 1 ;;
    130) exit 130 ;;
    *) MENU_KEYS_BROKEN=1  # no usable terminal: line prompt from now on
       read_line "$__mk_p" "$__mk_var" ;;
  esac
}
