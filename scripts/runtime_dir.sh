# shellcheck shell=sh
# Sourceable: familia_runtime_dir prints a private 0700 dir or fails (t835u).
# familia_scratch prints a fresh mktemp file inside it.
_fam_priv_ok() { # dir -> 0 if real dir, ours, no g/o bits
  [ -d "$1" ] && [ ! -L "$1" ] || return 1
  [ "$(ls -ldn "$1" | awk '{print $3}')" = "$(id -u)" ] || return 1
  case "$(ls -ld "$1" | cut -c5-10)" in ------) return 0;; *) return 1;; esac
}
familia_runtime_dir() {
  if [ -n "${XDG_RUNTIME_DIR:-}" ] && _fam_priv_ok "$XDG_RUNTIME_DIR"; then d=$XDG_RUNTIME_DIR/familia
  else b=${TMPDIR:-}; [ -z "$b" ] && [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/tmp" ] && b=$PREFIX/tmp; d=${b:-/tmp}/familia-$(id -u); fi
  (umask 077; mkdir "$d" 2>/dev/null); _fam_priv_ok "$d" || { echo "familia_runtime_dir: refuse unsafe $d" >&2; return 1; }
  printf '%s\n' "$d"
}
familia_scratch() { d=$(familia_runtime_dir) || return 1; (umask 077; mktemp "$d/${1:-scratch}.XXXXXX"); }
