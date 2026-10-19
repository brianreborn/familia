#!/bin/sh
# install-cli.sh: put `familia` on your PATH for this user. The code stays in this checkout;
# the only thing written is a 2-line shim (plus links to the man page / bash completion if present).
# Usage: sh scripts/install-cli.sh [install] [--dry-run] [--prefix DIR] [--force]
#        sh scripts/install-cli.sh uninstall [--dry-run] [--yes]   (removes exactly what install recorded)
#        sh scripts/install-cli.sh path --add|--remove [--dry-run] [--yes]
#        sh scripts/install-cli.sh status
# Where: shim  $XDG_BIN_HOME/familia (default ~/.local/bin/familia); Termux: $PREFIX/bin/familia
#        man   $XDG_DATA_HOME/man/man1/familia.1 (default ~/.local/share/...), only if man/familia.1 exists
#        bash  $XDG_DATA_HOME/bash-completion/completions/familia, only if the checkout ships one
#        --prefix DIR uses DIR/bin and DIR/share instead. Manifest: $XDG_STATE_HOME/familia/installed.txt
# Shell rc files are never edited unless you run `path --add` and say yes: it writes one block
# between "# >>> familia >>>" and "# <<< familia <<<" to ~/.profile; `path --remove` deletes only that block.
# Examples: sh scripts/install-cli.sh --dry-run
#           sh scripts/install-cli.sh path --add
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ACTION=install; SUB=""; DRY=0; YES=0; FORCE=0; OPT_PREFIX=""
say() { echo "familia-cli: $*"; }
die() { echo "familia-cli: error: $1" >&2; exit "${2:-1}"; }
abs() { case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s/%s\n' "$(pwd)" "$1" ;; esac; }
xdg() { case "${1:-}" in /*) printf '%s\n' "$1" ;; *) printf '%s\n' "$2" ;; esac; }  # XDG: relative = unset

while [ $# -gt 0 ]; do
  case "$1" in
    install) ACTION=install ;;
    uninstall|--uninstall) ACTION=uninstall ;;
    status) ACTION=status ;;
    path) ACTION=path ;;
    --add|--remove) SUB=$1 ;;
    --dry-run|-n|-WhatIf) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --force) FORCE=1 ;;
    --prefix) shift; [ $# -gt 0 ] || die "--prefix needs a directory" 2; OPT_PREFIX=$(abs "$1") ;;
    --prefix=*) OPT_PREFIX=$(abs "${1#--prefix=}") ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument '$1' (see --help)" 2 ;;
  esac
  shift
done
[ "$ACTION" != path ] || [ -n "$SUB" ] || die "path needs --add or --remove" 2

TERMUX=0
if [ -n "${TERMUX_VERSION:-}" ]; then TERMUX=1; else case "${PREFIX:-}" in */com.termux/*) TERMUX=1 ;; esac; fi
if [ -n "$OPT_PREFIX" ]; then BIN=$OPT_PREFIX/bin; DATA=$OPT_PREFIX/share
elif [ "$TERMUX" = 1 ]; then BIN=$PREFIX/bin; DATA=$PREFIX/share
else BIN=$(xdg "${XDG_BIN_HOME:-}" "$HOME/.local/bin"); DATA=$(xdg "${XDG_DATA_HOME:-}" "$HOME/.local/share"); fi
STATE=$(xdg "${XDG_STATE_HOME:-}" "$HOME/.local/state")/familia
MANIFEST=$STATE/installed.txt
PROFILE=${FAMILIA_PROFILE:-$HOME/.profile}
SHIM=$BIN/familia
BEGIN='# >>> familia >>>'; END='# <<< familia <<<'

sq() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
shim_text() { printf '#!/bin/sh\nexec %s "$@"\n' "$(sq "$ROOT/familia")"; }
is_shim() {  # a 2-line familia shim (ours, from any checkout)
  [ -f "$1" ] && [ ! -L "$1" ] && [ "$(wc -l < "$1" | tr -d ' ')" = 2 ] && [ "$(head -n 1 "$1")" = '#!/bin/sh' ] &&
    tail -n 1 "$1" | grep -q '^exec .*/familia'"'"'\{0,1\} "\$@"$'
}
in_manifest() { [ -f "$MANIFEST" ] && grep -Fqx -- "$1" "$MANIFEST"; }
record() { [ "$DRY" = 1 ] && return 0; mkdir -p "$STATE"; in_manifest "$1" || printf '%s\n' "$1" >> "$MANIFEST"; }
on_path() { case ":$PATH:" in *":$BIN:"*) return 0 ;; esac; return 1; }
show_dir() { case "$1" in "$HOME"/*) printf '$HOME/%s' "${1#"$HOME"/}" ;; *) printf '%s' "$1" ;; esac; }
path_line() { printf 'export PATH="%s:$PATH"' "$(show_dir "$BIN")"; }
block() {
  printf '%s\n# added by `familia path --add`; `familia path --remove` deletes this block\n' "$BEGIN"
  printf 'case ":$PATH:" in *":%s:"*) ;; *) %s ;; esac\n%s\n' "$(show_dir "$BIN")" "$(path_line)" "$END"
}
has_block() { [ -f "$PROFILE" ] && grep -Fqx -- "$BEGIN" "$PROFILE"; }
confirm() {  # confirm QUESTION: --yes, or y on a terminal
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || return 1
  printf '%s [y/N] ' "$1"; read -r a || return 1
  case "$a" in y|Y|yes|YES) return 0 ;; esac; return 1
}

link() {  # link SRC DEST: symlink a checkout file (man page, completion)
  if [ "$(readlink "$2" 2>/dev/null || true)" = "$1" ]; then say "up to date: $2"; record "$2"; return 0; fi
  if [ -e "$2" ] && [ ! -L "$2" ] && [ "$FORCE" != 1 ] && ! in_manifest "$2"; then
    say "skip $2: a file that familia did not write is there (use --force to replace it)"; return 0; fi
  if [ "$DRY" = 1 ]; then say "[dry-run] link $2 -> $1"; return 0; fi
  mkdir -p "$(dirname "$2")"; ln -sfn "$1" "$2"; record "$2"; say "linked $2 -> $1"
}

do_install() {
  [ -x "$ROOT/familia" ] || die "$ROOT/familia is missing or not executable"
  [ "$DRY" = 1 ] && say "dry run: nothing will be written"
  say "checkout: $ROOT (the code stays here; nothing is copied)"
  want=$(shim_text)
  if [ -f "$SHIM" ] && [ ! -L "$SHIM" ] && [ "$(cat "$SHIM")" = "$want" ]; then
    say "up to date: $SHIM"; record "$SHIM"
  elif [ -e "$SHIM" ] || [ -L "$SHIM" ]; then
    if ! is_shim "$SHIM" && [ "$FORCE" != 1 ]; then
      die "$SHIM exists and is not a familia shim; move it away or use --force"; fi
    if [ "$DRY" = 1 ]; then say "[dry-run] replace $SHIM (now: $(tail -n 1 "$SHIM" 2>/dev/null || echo '?'))"
    else rm -f "$SHIM"; printf '%s\n' "$want" > "$SHIM"; chmod 755 "$SHIM"; record "$SHIM"; say "updated $SHIM"; fi
  elif [ "$DRY" = 1 ]; then say "[dry-run] write $SHIM (2 lines):"; printf '%s\n' "$want" | sed 's/^/    /'
  else mkdir -p "$BIN"; printf '%s\n' "$want" > "$SHIM"; chmod 755 "$SHIM"; record "$SHIM"; say "wrote $SHIM"; fi

  if [ -f "$ROOT/man/familia.1" ]; then link "$ROOT/man/familia.1" "$DATA/man/man1/familia.1"
  else say "no man page in this checkout yet (man/familia.1); skipped"; fi
  comp=""; for c in completions/familia.bash completions/familia man/familia.bash-completion; do
    [ -f "$ROOT/$c" ] && { comp=$ROOT/$c; break; }; done
  if [ -n "$comp" ]; then link "$comp" "$DATA/bash-completion/completions/familia"
  else say "no bash completion in this checkout yet; skipped"; fi
  [ "$DRY" = 1 ] && say "[dry-run] record these files in $MANIFEST" || say "recorded in $MANIFEST"

  if on_path; then say "$(show_dir "$BIN") is on your PATH: run 'familia' from anywhere ('familia help')"
  else
    say "$(show_dir "$BIN") is not on your PATH yet. Add this one line to ~/.profile (or your shell's rc file):"
    echo "    $(path_line)"
    if "$ROOT/familia" path --help >/dev/null 2>&1; then how="$(show_dir "$SHIM") path --add"
    else how="sh $ROOT/scripts/install-cli.sh path --add"; fi
    say "or let familia add it for you (asks first; undo with --remove): $how"
  fi
}

do_uninstall() {
  if [ ! -s "$MANIFEST" ]; then say "nothing recorded in $MANIFEST; nothing to remove"; else
    say "files recorded in $MANIFEST:"
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      if [ -L "$f" ] || is_shim "$f"; then echo "    remove $f"
      elif [ -e "$f" ]; then echo "    keep   $f (changed since install; not a familia shim or link)"
      else echo "    gone   $f"; fi
    done < "$MANIFEST"
  fi
  has_block && echo "    remove the familia block from $PROFILE"
  if [ "$DRY" = 1 ]; then say "[dry-run] nothing removed"; return 0; fi
  if ! confirm "Remove these?"; then say "nothing removed (preview only; re-run with --yes to remove)"; return 0; fi
  if [ -s "$MANIFEST" ]; then
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      if [ -L "$f" ] || is_shim "$f"; then rm -f "$f"; say "removed $f"; fi
    done < "$MANIFEST"
  fi
  rm -f "$MANIFEST"; rmdir "$STATE" 2>/dev/null || true
  has_block && remove_block
  say "uninstalled; the checkout $ROOT was not touched"
}

remove_block() {
  tmp=$(mktemp "${TMPDIR:-/tmp}/familia-profile.XXXXXX")
  awk -v b="$BEGIN" -v e="$END" '$0==b{skip=1; next} skip&&$0==e{skip=0; next} !skip' "$PROFILE" > "$tmp"
  cat "$tmp" > "$PROFILE"; rm -f "$tmp"   # rewrite in place: keeps the file's owner and mode
  say "removed the familia block from $PROFILE"
}

do_path() {
  if [ "$SUB" = --remove ]; then
    has_block || { say "no familia block in $PROFILE; nothing to remove"; return 0; }
    if [ "$DRY" = 1 ]; then say "[dry-run] would delete the lines from '$BEGIN' to '$END' in $PROFILE"; return 0; fi
    confirm "Remove the familia PATH block from $PROFILE?" || die "not removed (no terminal to ask; re-run with --yes)" 2
    remove_block; return 0
  fi
  if has_block && [ "$(awk -v b="$BEGIN" -v e="$END" '$0==b{p=1} p{print} p&&$0==e{exit}' "$PROFILE")" = "$(block)" ]; then
    say "$PROFILE already has the familia block; nothing to do"; return 0; fi
  say "this block would be added to $PROFILE:"; block | sed 's/^/    /'
  if [ "$DRY" = 1 ]; then say "[dry-run] $PROFILE not changed"; return 0; fi
  confirm "Add it to $PROFILE?" || die "not added (no terminal to ask; re-run with --yes, or add the line yourself)" 2
  has_block && remove_block
  if [ -s "$PROFILE" ] && [ "$(tail -c 1 "$PROFILE" | od -An -c | tr -d ' ')" != '\n' ]; then echo >> "$PROFILE"; fi
  block >> "$PROFILE"
  say "added. It takes effect at your next login; for this shell: $(path_line)"
  for f in "$HOME/.bash_profile" "$HOME/.bash_login"; do
    [ -f "$f" ] && say "note: bash login shells read $f instead of ~/.profile; make sure it sources ~/.profile"
  done
  return 0
}

do_status() {
  if is_shim "$SHIM"; then say "shim: $SHIM -> $(tail -n 1 "$SHIM" | sed 's/^exec //; s/ "\$@"$//')"; else say "shim: not installed ($SHIM)"; fi
  on_path && say "PATH: $(show_dir "$BIN") is on PATH" || say "PATH: $(show_dir "$BIN") is NOT on PATH"
  has_block && say "profile: familia block present in $PROFILE" || say "profile: no familia block in $PROFILE"
  if [ -s "$MANIFEST" ]; then say "manifest $MANIFEST:"; sed 's/^/    /' "$MANIFEST"; else say "manifest: none"; fi
}

case "$ACTION" in
  install) do_install ;; uninstall) do_uninstall ;; path) do_path ;; status) do_status ;;
esac
