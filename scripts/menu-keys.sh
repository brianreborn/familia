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
# Sourcing only defines functions (no stty, no raw mode, no traps). Example:
#   . scripts/menu-keys.sh; menu_key_read "Choose 1-3: " choice 3
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi
__menu_keys_restore() {  # put back the tty saved by menu_key_read (safety net if the picker died)
  [ -n "${__MENU_KEYS_STTY:-}" ] && stty "$__MENU_KEYS_STTY" 2>/dev/null
  [ -n "${__MENU_KEYS_STTY:-}" ] && printf '\033[?2004l' >&2
  return 0
}
menu_key_read() {  # menu_key_read PROMPT VAR COUNT ; returns 1 on EOF
  local __mk_p=$1 __mk_var=$2 __mk_n=${3:-0} __mk_out __mk_rc=0 __mk_int __mk_exit
  if [ "${FAMILIA_MENU_ARROWS:-1}" = 0 ] || [ "${MENU_KEYS_BROKEN:-0}" = 1 ] || [ "${FAMILIA_NO_TTY:-}" = 1 ] || ! [ -t 1 ] || ! [ -t 2 ]; then
    read_line "$__mk_p" "$__mk_var"; return
  fi
  # The picker restores the tty itself; this is the net for a picker that is killed.
  # Traps live only for this call: the caller's INT/EXIT traps are put back before return.
  __MENU_KEYS_STTY=$(stty -g 2>/dev/null) || __MENU_KEYS_STTY=""
  __mk_int=$(trap -p INT); __mk_exit=$(trap -p EXIT)
  trap '__menu_keys_restore; trap - INT; kill -INT $$' INT
  trap '__menu_keys_restore' EXIT
  __mk_out=$("${PY:-python3}" "${ROOT:-.}/scripts/menu_keys.py" pick --prompt "$__mk_p" --count "$__mk_n" --prev --next) || __mk_rc=$?
  __menu_keys_restore
  eval "${__mk_int:-trap - INT}"; eval "${__mk_exit:-trap - EXIT}"
  __MENU_KEYS_STTY=""
  case $__mk_rc in
    0) printf -v "$__mk_var" '%s' "$__mk_out"; return 0 ;;
    4) return 1 ;;
    130) kill -INT $$; exit 130 ;;  # Ctrl-C: stop like the line prompt does (caller's INT trap runs)
    *) MENU_KEYS_BROKEN=1  # picker missing, refused (M2 probe) or died: line prompt from now on
       read_line "$__mk_p" "$__mk_var" ;;
  esac
}
