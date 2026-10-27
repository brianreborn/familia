#!/bin/sh
# FAMILIA: Termux (Android) OS packages — list / optionally install.
# Pure POSIX. Prefer: sh install/deps.sh …
# Usage:
#   sh install/termux/deps.sh
#   sh install/termux/deps.sh --install [--yes] [--dry-run] [--profile base|build]
# Confirmed package names (Termux repos, 2026-10):
#   getconf, git, python, python-pip, openssh, llama-cpp,
#   clang, cmake, ninja  (build profile)
#   pytest: python-pytest if present, else pip install pytest
set -eu
case "${1:-}" in -h|--help) cat <<'USAGE'
deps.sh (Termux): List / install packages familia needs on Android Termux.
Usage: sh install/termux/deps.sh [--install] [--yes] [--dry-run] [--profile base|build]
  base (default): git python getconf openssh (+ llama-cpp when installing runtime)
  build:          base + clang cmake ninja (code-bootstraps scripts/build-termux.sh)
USAGE
  exit 0 ;; esac

INSTALL=0; YES=0; DRY=0; PROFILE=base; RUNTIME=1
for a in "$@"; do
  case "$a" in
    --install) INSTALL=1 ;;
    --yes|-y) YES=1 ;;
    --dry-run|-n) DRY=1 ;;
    --no-runtime) RUNTIME=0 ;;
    base|build) PROFILE=$a ;;
    --profile=*) PROFILE=${a#--profile=} ;;
  esac
done
prev=""
for a in "$@"; do
  if [ "$prev" = "--profile" ]; then PROFILE=$a; fi
  prev=$a
done
case "$PROFILE" in base|build) ;; *) echo "familia-deps: unknown --profile $PROFILE" >&2; exit 2 ;; esac

have_cmd() { command -v "$1" >/dev/null 2>&1; }
have_pytest() {
  python -m pytest --version >/dev/null 2>&1 && return 0
  python3 -m pytest --version >/dev/null 2>&1 && return 0
  have_cmd pytest && return 0
  return 1
}
have_yaml() {
  python -c 'import yaml' >/dev/null 2>&1 && return 0
  python3 -c 'import yaml' >/dev/null 2>&1 && return 0
  return 1
}

# Abstract → Termux pkg name (install list). Checks use commands.
# getconf: confirmed Termux package name `getconf` (Brian 2026-10-27).
NEED="git:git python:python getconf:getconf"
[ "$RUNTIME" = 1 ] && NEED="$NEED llama-cpp:llama-server"
NEED="$NEED openssh:ssh"  # optional but common for phone SSH; listed as soft below
SOFT="openssh:ssh"
BUILD="clang:clang cmake:cmake ninja:ninja"

missing=""; present=""; soft_missing=""
check_pair() {
  # $1=pkg $2=cmd $3=bucket var name prefix
  pkg=$1; cmd=$2
  if have_cmd "$cmd"; then present="$present $pkg"
  else
    case "$3" in
      soft) soft_missing="$soft_missing $pkg" ;;
      *) missing="$missing $pkg" ;;
    esac
  fi
}
for pair in $NEED; do
  case "$pair" in openssh:*) continue ;; esac  # handled as soft
  check_pair "${pair%%:*}" "${pair#*:}" hard
done
for pair in $SOFT; do
  check_pair "${pair%%:*}" "${pair#*:}" soft
done
if have_yaml; then present="$present pyyaml"; else missing="$missing pyyaml"; fi
if have_pytest; then present="$present pytest"; else missing="$missing pytest"; fi
if [ "$PROFILE" = build ]; then
  for pair in $BUILD; do check_pair "${pair%%:*}" "${pair#*:}" hard; done
fi

say() { echo "familia-deps: $*" >&2; }
say "platform=termux profile=$PROFILE"
say "present:${present:- (none)}"
say "missing:${missing:- (none)}"
[ -n "${soft_missing# }" ] && say "optional-missing:${soft_missing}"
say "home of the safe-mode *build* AI: pinned code-bootstraps-llama.cpp (build-termux.sh)"

# Map to pkg install list
pkgs=""
pip_pkgs=""
for m in $missing $soft_missing; do
  case "$m" in
    pyyaml) pip_pkgs="$pip_pkgs pyyaml" ;;  # Termux often has no python-yaml pkg; pip is fine
    pytest)
      # Prefer pkg if it exists in the repo index; else pip.
      if pkg search python-pytest 2>/dev/null | grep -q '^python-pytest'; then
        pkgs="$pkgs python-pytest"
      else
        pip_pkgs="$pip_pkgs pytest"
      fi
      ;;
    llama-cpp) pkgs="$pkgs llama-cpp" ;;
    *) pkgs="$pkgs $m" ;;
  esac
done
pkgs=$(echo "$pkgs" | sed 's/^ *//;s/  */ /g')
pip_pkgs=$(echo "$pip_pkgs" | sed 's/^ *//;s/  */ /g')

if [ -z "$pkgs" ] && [ -z "$pip_pkgs" ]; then
  say "all required packages look present"
  exit 0
fi

CMD=""
[ -n "$pkgs" ] && CMD="pkg install -y $pkgs"
[ -n "$pip_pkgs" ] && {
  if [ -n "$CMD" ]; then CMD="$CMD && pip install --quiet $pip_pkgs"
  else CMD="pip install --quiet $pip_pkgs"; fi
}

say "suggested: $CMD"
if [ "$INSTALL" != 1 ]; then
  say "re-run with --install to install them (add --yes for non-interactive)"
  exit 1
fi
if [ "$DRY" = 1 ]; then say "[dry-run] $CMD"; exit 0; fi
if [ "$YES" != 1 ] && [ -r /dev/tty ]; then
  printf 'familia-deps: install missing Termux packages now? [y/N] ' >&2
  read -r ans < /dev/tty || ans=n
  case "$ans" in y|Y|yes) ;; *) say "aborted"; exit 1 ;; esac
fi
if [ -n "$pkgs" ]; then
  # shellcheck disable=SC2086
  pkg install -y $pkgs
fi
if [ -n "$pip_pkgs" ]; then
  # shellcheck disable=SC2086
  pip install --quiet $pip_pkgs || say "warning: pip install failed for:$pip_pkgs"
fi
say "done"
