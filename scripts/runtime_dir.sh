# shellcheck shell=sh
# Sourceable: familia_runtime_dir prints a private 0700 dir or fails (t835u).
# Order (matches runtime_dir.py / b041fb8): $XDG_RUNTIME_DIR/familia, then
# ${XDG_CACHE_HOME:-$HOME/.cache}/familia/run, then ${TMPDIR:-/tmp}/familia-<uid>.
# Each rejected candidate is logged to stderr with its reason.
# familia_scratch prints a fresh mktemp file inside it.
_fam_priv_why() { # dir -> prints reason and returns 1 if unsafe
  if [ -L "$1" ]; then echo "symlink"; return 1; fi
  if [ ! -d "$1" ]; then echo "not a directory"; return 1; fi
  _o=$(ls -ldn "$1" | awk '{print $3}')
  [ "$_o" = "$(id -u)" ] || { echo "foreign owner uid=$_o"; return 1; }
  case "$(ls -ld "$1" | cut -c5-10)" in ------) return 0;; *) echo "group/other bits set"; return 1;; esac
}
_fam_try() { # candidate -> 0 and prints dir, or logs reason
  (umask 077; mkdir "$1" 2>/dev/null)
  if _r=$(_fam_priv_why "$1"); then printf '%s\n' "$1"; return 0; fi
  echo "familia_runtime_dir: reject $1: $_r" >&2; return 1
}
familia_runtime_dir() {
  if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
    if _r=$(_fam_priv_why "$XDG_RUNTIME_DIR"); then _fam_try "$XDG_RUNTIME_DIR/familia" && return 0
    else echo "familia_runtime_dir: reject $XDG_RUNTIME_DIR: $_r" >&2; fi
  fi
  _c=${XDG_CACHE_HOME:-}; [ -z "$_c" ] && [ -n "${HOME:-}" ] && _c=$HOME/.cache
  if [ -n "$_c" ]; then
    [ -d "$_c/familia" ] || (umask 077; mkdir -p "$_c/familia" 2>/dev/null)
    _fam_try "$_c/familia/run" && return 0
  fi
  b=${TMPDIR:-}; [ -z "$b" ] && [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/tmp" ] && b=$PREFIX/tmp
  _fam_try "${b:-/tmp}/familia-$(id -u)"
}
familia_scratch() { d=$(familia_runtime_dir) || return 1; (umask 077; mktemp "$d/${1:-scratch}.XXXXXX"); }
