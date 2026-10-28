#!/bin/sh
# FAMILIA: declare and optionally install OS packages the Linux/macOS installer
# (and code-bootstraps source builds) need. Pure POSIX /bin/sh.
# Does not run the full installer — only the platform deps.
# Usage:
#   sh install/linux/deps.sh                       # print what is missing / present
#   sh install/linux/deps.sh --install             # install missing (asks, or --yes)
#   sh install/linux/deps.sh --yes --install
#   sh install/linux/deps.sh --profile build --install
# Prefer the dispatcher: sh install/deps.sh …
set -eu
case "${1:-}" in -h|--help) cat <<'USAGE'
deps.sh: List (and optionally install) packages familia needs on this Linux/macOS host.
Usage: sh install/linux/deps.sh [--install] [--yes] [--dry-run] [--profile base|build]
  --install           install anything missing (apt/dnf/pacman/zypper/brew)
  --yes               non-interactive install
  --dry-run           show the package manager command; change nothing
  --profile base      git curl python3 tar unzip pyyaml pytest (default)
  --profile build     base + cmake ninja C/C++ compiler (for code-bootstraps llama.cpp builds)
getconf: usually in glibc/coreutils (Linux) or the system; no separate package on most distros.
  macOS: getconf is in the base system. See docs/safe-mode-bootstrap.md.
USAGE
  exit 0 ;; esac

INSTALL=0; YES=0; DRY=0; PROFILE=base
for a in "$@"; do
  case "$a" in
    --install) INSTALL=1 ;;
    --yes|-y) YES=1 ;;
    --dry-run|-n) DRY=1 ;;
    --profile) ;; # next arg handled below
    base|build) PROFILE=$a ;;
    --profile=*) PROFILE=${a#--profile=} ;;
  esac
done
# Allow --profile build as two tokens
prev=""
for a in "$@"; do
  if [ "$prev" = "--profile" ]; then PROFILE=$a; fi
  prev=$a
done
case "$PROFILE" in base|build) ;; *) echo "familia-deps: unknown --profile $PROFILE (base|build)" >&2; exit 2 ;; esac

# Abstract names checked below; mapped to distro packages later.
# getconf: document only — almost always present via glibc/coreutils (not a separate pkg).
NEED_CMDS="git:git curl:curl python3:python3 tar:tar unzip:unzip"
BUILD_CMDS="cmake:cmake ninja:ninja"
# Compilers: any of these counts as "have a C++ toolchain"
have_cmd() { command -v "$1" >/dev/null 2>&1; }
have_yaml() { python3 -c 'import yaml' >/dev/null 2>&1; }
have_pytest() {
  python3 -m pytest --version >/dev/null 2>&1 && return 0
  have_cmd pytest && return 0
  return 1
}
have_cxx() {
  have_cmd c++ && return 0
  have_cmd g++ && return 0
  have_cmd clang++ && return 0
  return 1
}

missing=""
present=""
for pair in $NEED_CMDS; do
  cmd=${pair#*:}; pkg=${pair%%:*}
  if have_cmd "$cmd"; then present="$present $pkg"; else missing="$missing $pkg"; fi
done
if have_yaml; then present="$present python3-yaml"; else missing="$missing python3-yaml"; fi
if have_pytest; then present="$present pytest"; else missing="$missing pytest"; fi
if have_cmd getconf; then present="$present getconf"; else
  # Rare on stripped containers; hint only — not a separate apt package on Debian/Ubuntu.
  missing="$missing getconf-hint"
fi

if [ "$PROFILE" = build ]; then
  for pair in $BUILD_CMDS; do
    cmd=${pair#*:}; pkg=${pair%%:*}
    if have_cmd "$cmd"; then present="$present $pkg"; else missing="$missing $pkg"; fi
  done
  if have_cxx; then present="$present c++"; else missing="$missing build-essential"; fi
fi

say() { echo "familia-deps: $*" >&2; }
say "profile=$PROFILE"
say "present:${present:- (none)}"
say "missing:${missing:- (none)}"
say "note: getconf comes from glibc/coreutils (Linux) or the base system (macOS); install build-essential/xcode only if missing"
say "home of the safe-mode *build* AI: pinned code-bootstraps-llama.cpp (see docs/safe-mode-bootstrap.md)"

# Strip documentation-only hints before trying to install
install_missing=""
for m in $missing; do
  case "$m" in getconf-hint) ;; *) install_missing="$install_missing $m" ;; esac
done

if [ -z "${install_missing# }" ] && [ -z "${missing# }" ]; then
  say "all required packages look present"
  exit 0
fi
if [ -z "${install_missing# }" ]; then
  say "only documentation hints missing (getconf); nothing to install via the package manager"
  exit 0
fi

detect_pm() {
  if have_cmd apt-get; then echo apt
  elif have_cmd dnf; then echo dnf
  elif have_cmd pacman; then echo pacman
  elif have_cmd zypper; then echo zypper
  elif have_cmd brew; then echo brew
  else echo unknown
  fi
}
PM=$(detect_pm)
# Map abstract names to distro packages
pkgs=""
for m in $install_missing; do
  case "$PM/$m" in
    apt/python3-yaml) pkgs="$pkgs python3-yaml" ;;
    dnf/python3-yaml|zypper/python3-yaml) pkgs="$pkgs python3-pyyaml" ;;
    pacman/python3-yaml) pkgs="$pkgs python-yaml" ;;
    brew/python3-yaml) pkgs="$pkgs pyyaml" ;;
    apt/pytest) pkgs="$pkgs python3-pytest" ;;
    dnf/pytest|zypper/pytest) pkgs="$pkgs python3-pytest" ;;
    pacman/pytest) pkgs="$pkgs python-pytest" ;;
    brew/pytest) pkgs="$pkgs pytest" ;;
    apt/build-essential) pkgs="$pkgs build-essential" ;;
    dnf/build-essential|zypper/build-essential) pkgs="$pkgs gcc gcc-c++ make" ;;
    pacman/build-essential) pkgs="$pkgs base-devel" ;;
    brew/build-essential) pkgs="$pkgs" ;; # Xcode CLT; brew can't install it
    apt/ninja) pkgs="$pkgs ninja-build" ;;
    dnf/ninja|zypper/ninja) pkgs="$pkgs ninja-build" ;;
    pacman/ninja|brew/ninja) pkgs="$pkgs ninja" ;;
    apt/*|dnf/*|zypper/*|pacman/*|brew/*) pkgs="$pkgs $m" ;;
    *) pkgs="$pkgs $m" ;;
  esac
done
pkgs=$(echo "$pkgs" | sed 's/^ *//;s/  */ /g')

if [ -z "$pkgs" ]; then
  say "nothing mapped for $PM (e.g. macOS needs Xcode CLT: xcode-select --install)"
  [ "$INSTALL" = 1 ] || exit 1
  exit 0
fi

# root (e.g. a fresh root-only box) needs no sudo, and may not have it installed
SUDO=sudo; [ "$(id -u)" = 0 ] && SUDO=""
case "$PM" in
  apt) CMD="${SUDO:+$SUDO }apt-get update && ${SUDO:+$SUDO }apt-get install -y $pkgs" ;;
  dnf) CMD="${SUDO:+$SUDO }dnf install -y $pkgs" ;;
  pacman) CMD="${SUDO:+$SUDO }pacman -Sy --needed --noconfirm $pkgs" ;;
  zypper) CMD="${SUDO:+$SUDO }zypper install -y $pkgs" ;;
  brew) CMD="brew install $pkgs" ;;
  *) say "unknown package manager; install manually:$install_missing"; exit 1 ;;
esac

say "suggested: $CMD"
if [ "$INSTALL" != 1 ]; then
  say "re-run with --install to install them (add --yes for non-interactive)"
  exit 1
fi
if [ "$DRY" = 1 ]; then say "[dry-run] $CMD"; exit 0; fi
if [ "$YES" != 1 ] && [ -r /dev/tty ]; then
  printf 'familia-deps: install missing packages now? [y/N] ' >&2
  read -r ans < /dev/tty || ans=n
  case "$ans" in y|Y|yes) ;; *) say "aborted"; exit 1 ;; esac
fi
sh -c "$CMD"
say "done"
