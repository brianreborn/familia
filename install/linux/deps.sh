#!/bin/sh
# FAMILIA: declare and optionally install OS packages the Linux/macOS installer needs.
# Pure POSIX /bin/sh. Does not run the full installer — only the platform deps.
# Usage:
#   sh install/linux/deps.sh            # print what is missing / present
#   sh install/linux/deps.sh --install  # install missing (asks, or --yes)
#   sh install/linux/deps.sh --yes --install
set -eu
case "${1:-}" in -h|--help) cat <<'USAGE'
deps.sh: List (and optionally install) packages familia needs on this Linux/macOS host.
Usage: sh install/linux/deps.sh [--install] [--yes] [--dry-run]
  --install   install anything missing (apt/dnf/pacman/zypper/brew)
  --yes       non-interactive install
  --dry-run   show the package manager command; change nothing
USAGE
  exit 0 ;; esac

INSTALL=0; YES=0; DRY=0
for a in "$@"; do
  case "$a" in --install) INSTALL=1 ;; --yes|-y) YES=1 ;; --dry-run|-n) DRY=1 ;; esac
done

# name:command (empty command = package itself is the check)
# python3-yaml: python3 -c 'import yaml'
NEED_CMDS="git:git curl:curl python3:python3 tar:tar"
NEED_PY="yaml:python3-yaml"

have_cmd() { command -v "$1" >/dev/null 2>&1; }
have_yaml() { python3 -c 'import yaml' >/dev/null 2>&1; }

missing=""
present=""
for pair in $NEED_CMDS; do
  cmd=${pair#*:}; pkg=${pair%%:*}
  if have_cmd "$cmd"; then present="$present $pkg"; else missing="$missing $pkg"; fi
done
if have_yaml; then present="$present python3-yaml"; else missing="$missing python3-yaml"; fi

# unzip only needed when a release asset is .zip
if ! have_cmd unzip; then missing="$missing unzip"; else present="$present unzip"; fi

say() { echo "familia-deps: $*" >&2; }
say "present:${present:- (none)}"
say "missing:${missing:- (none)}"

if [ -z "${missing# }" ]; then
  say "all required packages look present"
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
for m in $missing; do
  case "$PM/$m" in
    apt/python3-yaml) pkgs="$pkgs python3-yaml" ;;
    dnf/python3-yaml|zypper/python3-yaml) pkgs="$pkgs python3-pyyaml" ;;
    pacman/python3-yaml) pkgs="$pkgs python-yaml" ;;
    brew/python3-yaml) pkgs="$pkgs pyyaml" ;;  # usually comes with python; best-effort
    apt/*|dnf/*|zypper/*|pacman/*|brew/*) pkgs="$pkgs $m" ;;
    *) pkgs="$pkgs $m" ;;
  esac
done
pkgs=$(echo "$pkgs" | sed 's/^ *//')

case "$PM" in
  apt) CMD="sudo apt-get install -y $pkgs" ;;
  dnf) CMD="sudo dnf install -y $pkgs" ;;
  pacman) CMD="sudo pacman -S --needed --noconfirm $pkgs" ;;
  zypper) CMD="sudo zypper install -y $pkgs" ;;
  brew) CMD="brew install $pkgs" ;;
  *) say "unknown package manager; install manually:$missing"; exit 1 ;;
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
# shellcheck disable=SC2086
set -- $CMD
"$@"
say "done"
