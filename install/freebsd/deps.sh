#!/bin/sh
# FAMILIA: FreeBSD deps helper (honest listing + opt-in pkg install).
# Angel / Uriel: runtime installer is unsupported; build llama.cpp from the
# pinned code-bootstraps-llama.cpp with:
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
getconf: FreeBSD base (no pkg). llama-server: build from code-bootstraps, do not expect a binary pkg.
Opt-in only: this script never runs pkg without --install.
USAGE
  exit 0 ;; esac

INSTALL=0; YES=0; DRY=0; PROFILE=base
for a in "$@"; do
  case "$a" in
    --install) INSTALL=1 ;;
    --yes|-y) YES=1 ;;
    --dry-run|-n) DRY=1 ;;
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
have_yaml() { python3 -c 'import yaml' >/dev/null 2>&1; }
have_pytest() {
  python3 -m pytest --version >/dev/null 2>&1 && return 0
  have_cmd pytest && return 0
  return 1
}
have_cxx() { have_cmd c++ || have_cmd clang++ || have_cmd g++; }

missing=""; present=""
for pair in git:git curl:curl python3:python3 tar:tar; do
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

say() { echo "familia-deps: $*" >&2; }
say "platform=FreeBSD profile=$PROFILE"
say "present:${present:- (none)}"
say "missing:${missing:- (none)}"
say "pkg names (reference): git curl python3 py311-yaml py311-pytest cmake ninja llvm"
say "getconf: FreeBSD base — no package"
say "llama.cpp: BUILD_DIR=build-freebsd GPU=off  (from code-bootstraps-llama.cpp/scripts/build-linux.sh)"
say "home of the safe-mode *build* AI: pinned code-bootstraps-llama.cpp"

# Map to FreeBSD pkg names (best-effort; py version may differ)
pkgs=""
for m in $missing; do
  case "$m" in
    getconf*) ;; # base
    pyyaml) pkgs="$pkgs py311-yaml" ;;
    pytest) pkgs="$pkgs py311-pytest" ;;
    llvm-or-gcc) pkgs="$pkgs llvm" ;;
    *) pkgs="$pkgs $m" ;;
  esac
done
pkgs=$(echo "$pkgs" | sed 's/^ *//;s/  */ /g')

if [ -z "$pkgs" ]; then
  say "all required packages look present (or only base tools were missing)"
  exit 0
fi

CMD="pkg install -y $pkgs"
say "suggested: $CMD"
if [ "$INSTALL" != 1 ]; then
  say "re-run with --install to install them (add --yes for non-interactive). Angel: opt-in only."
  exit 1
fi
if [ "$DRY" = 1 ]; then say "[dry-run] $CMD"; exit 0; fi
if [ "$YES" != 1 ] && [ -r /dev/tty ]; then
  printf 'familia-deps: run pkg install for missing packages now? [y/N] ' >&2
  read -r ans < /dev/tty || ans=n
  case "$ans" in y|Y|yes) ;; *) say "aborted"; exit 1 ;; esac
fi
# shellcheck disable=SC2086
pkg install -y $pkgs
say "done"
