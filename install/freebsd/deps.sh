#!/bin/sh
# FAMILIA: FreeBSD deps helper (honest listing + opt-in pkg install).
# The FreeBSD installer builds llama.cpp from the pinned brianreborn fork.
# For a direct code-bootstraps build:
#   BUILD_DIR=build-freebsd GPU=off scripts/build-linux.sh
# getconf is in the FreeBSD base system (no package).
# Usage:
#   sh install/freebsd/deps.sh
#   sh install/freebsd/deps.sh --install [--yes] [--dry-run] [--profile base|build]
set -eu
case "${1:-}" in -h|--help) cat <<'USAGE'
deps.sh (FreeBSD): List packages useful for familia + code-bootstraps source builds.
Usage: sh install/freebsd/deps.sh [--install] [--yes] [--dry-run] [--profile base|build]
  base:  git curl python3 pyyaml pytest (pkg names below)
  build: base + cmake ninja gcc/llvm toolchain
getconf: FreeBSD base (no pkg). install-familia.sh builds pinned fork source b12032; not the llama-cpp pkg.
Opt-in only: this script never runs pkg without --install.
USAGE
  exit 0 ;; esac

case $0 in */*) LIB=${0%/*} ;; *) LIB=. ;; esac   # no dirname: deps.sh runs on a bare PATH
LIB=$(CDPATH='' cd -- "$LIB/../../lib" && pwd)
MK_TAG=familia-deps
# shellcheck source=SCRIPTDIR/../../lib/msg.mk
. "$LIB/msg.mk"    # say
# shellcheck source=SCRIPTDIR/../../lib/deps.mk
. "$LIB/deps.mk"   # deps_args, deps_confirm
deps_args "$@"
case "$PROFILE" in base|build) ;; *) echo "familia-deps: unknown --profile $PROFILE" >&2; exit 2 ;; esac

have_cmd() { command -v "$1" >/dev/null 2>&1; }
have_yaml() { python3 -c 'import yaml' >/dev/null 2>&1; }
have_pytest() {
  python3 -m pytest --version >/dev/null 2>&1 && return 0
  have_cmd pytest && return 0
  return 1
}
have_cxx() { have_cmd c++ || have_cmd clang++ || have_cmd g++; }

missing=""; present=""
for pair in git:git curl:curl python3:python3; do  # tar: FreeBSD base
  cmd=${pair#*:}; pkg=${pair%%:*}
  if have_cmd "$cmd"; then present="$present $pkg"; else missing="$missing $pkg"; fi
done
if have_cmd getconf; then present="$present getconf(base)"; else missing="$missing getconf(base-missing!)"; fi
if have_yaml; then present="$present pyyaml"; else missing="$missing pyyaml"; fi
if have_pytest; then present="$present pytest"; else missing="$missing pytest"; fi
if [ "$PROFILE" = build ]; then
  for pair in cmake:cmake ninja:ninja; do
    cmd=${pair#*:}; pkg=${pair%%:*}
    if have_cmd "$cmd"; then present="$present $pkg"; else missing="$missing $pkg"; fi
  done
  if have_cxx; then present="$present c++"; else missing="$missing llvm-or-gcc"; fi
fi

say "platform=FreeBSD profile=$PROFILE"
say "present:${present:- (none)}"
say "missing:${missing:- (none)}"
PYV=311; command -v python3 >/dev/null 2>&1 && PYV=$(python3 -c 'import sys; print("%d%d" % sys.version_info[:2])')
say "pkg names (reference): git curl python3 py$PYV-pyyaml py$PYV-pytest cmake ninja llvm"
say "getconf: FreeBSD base — no package"
say "llama.cpp: BUILD_DIR=build-freebsd GPU=off  (from code-bootstraps-llama.cpp/scripts/build-linux.sh)"
say "home of the safe-mode *build* AI: pinned code-bootstraps-llama.cpp"

# Map to FreeBSD pkg names (best-effort; py version may differ)
pkgs=""
for m in $missing; do
  case "$m" in
    getconf*) ;; # base
    pyyaml) pkgs="$pkgs py$PYV-pyyaml" ;;
    pytest) pkgs="$pkgs py$PYV-pytest" ;;
    llvm-or-gcc) pkgs="$pkgs llvm" ;;
    *) pkgs="$pkgs $m" ;;
  esac
done
pkgs=$(echo "$pkgs" | sed 's/^ *//;s/  */ /g')

if [ -z "$pkgs" ]; then
  say "all required packages look present (or only base tools were missing)"
  exit 0
fi

if [ "$(id -u)" = 0 ]; then
  ESC=""
elif have_cmd doas; then
  ESC=doas
elif have_cmd sudo; then
  ESC=sudo
else
  say "pkg install needs root; install manually: pkg install -y $pkgs"
  exit 1
fi
CMD="${ESC:+$ESC }pkg install -y $pkgs"
deps_confirm "$CMD" "run pkg install for missing packages now?" ". Angel: opt-in only."
if [ -n "$ESC" ]; then
  # shellcheck disable=SC2086
  $ESC pkg install -y $pkgs
else
  # shellcheck disable=SC2086
  pkg install -y $pkgs
fi
say "done"
