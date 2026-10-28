#!/bin/sh
# FAMILIA: platform deps dispatcher — install the local packages you need to
# *build* (and run) on this host. Anchors the safe-mode bootstrap path:
#   docs/safe-mode-bootstrap.md  +  pinned code-bootstraps-llama.cpp
# Usage:
#   sh install/deps.sh                 # detect platform; list present / missing
#   sh install/deps.sh --install       # install missing (asks, or --yes)
#   sh install/deps.sh --yes --install
#   sh install/deps.sh --profile build # also want cmake/ninja/compilers (source builds)
#   sh install/deps.sh --dry-run
# Flags are forwarded to the platform helper.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

case "${1:-}" in -h|--help) cat <<'USAGE'
deps.sh: Install local OS packages familia (and code-bootstraps) need on this host.
Usage: sh install/deps.sh [--install] [--yes] [--dry-run] [--profile base|build] [--help]
  --install          install anything missing
  --yes / -y         non-interactive install
  --dry-run / -n     show the package manager command; change nothing
  --profile base     runtime + tests (default): git, curl, python, tar, pyyaml, pytest, …
  --profile build    also compilers/cmake/ninja for source builds (code-bootstraps)
Dispatches to:
  install/linux/deps.sh     Linux / macOS (apt/dnf/pacman/zypper/brew)
  install/termux/deps.sh    Android Termux (pkg)
  install/freebsd/deps.sh   FreeBSD (pkg; opt-in --install)
  install/windows/deps.ps1  Windows (check + winget/choco hints; no silent mass install)
USAGE
  exit 0 ;; esac

# Detect platform. Termux exports PREFIX under com.termux; uname alone is Linux.
. "$ROOT/lib/os.mk"   # mk_is_termux
is_termux() { mk_is_termux || [ -d /data/data/com.termux/files/usr ]; }

OS=$(uname -s 2>/dev/null || echo unknown)
MK_TAG=familia-deps; . "$ROOT/lib/msg.mk"   # say

if is_termux; then
  say "platform=termux → install/termux/deps.sh"
  exec sh "$ROOT/install/termux/deps.sh" "$@"
fi

case "$OS" in
  Linux|Darwin)
    say "platform=$OS → install/linux/deps.sh"
    exec sh "$ROOT/install/linux/deps.sh" "$@"
    ;;
  FreeBSD)
    say "platform=FreeBSD → install/freebsd/deps.sh"
    exec sh "$ROOT/install/freebsd/deps.sh" "$@"
    ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    say "platform=Windows → install/windows/deps.ps1"
    if command -v powershell.exe >/dev/null 2>&1; then
      exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$ROOT/install/windows/deps.ps1" "$@"
    elif command -v pwsh >/dev/null 2>&1; then
      exec pwsh -NoProfile -ExecutionPolicy Bypass -File "$ROOT/install/windows/deps.ps1" "$@"
    else
      say "no PowerShell; open install/windows/deps.ps1 by hand (winget/choco hints)"
      exit 1
    fi
    ;;
  *)
    say "unsupported uname '$OS'. See docs/safe-mode-bootstrap.md and docs/install.md"
    exit 1
    ;;
esac
