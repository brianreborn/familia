#!/bin/sh
# FAMILIA: Top-level super-project installer.
# Pure POSIX /bin/sh.
# Two clicks:
#   curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install.sh | sh
# Click 1 is running the command. Click 2 is the donation tap-through.
set -eu
case "${1:-}" in -h|--help) cat <<'USAGE'
install.sh: Install familia into ~/familia (or $INSTALL_PREFIX), sync the pinned parts, then start it.
Usage:
  sh install.sh [--dry-run] [--yes] [--no-start] [--no-path]
    --dry-run   say what would happen; change nothing
    --yes       non-interactive: acknowledge the notice and accept licenses (the summary is still printed)
    --no-start  stop after setup (same as INSTALL_NO_START=1)
    --no-path   do not put `familia` on PATH (default: 2-line shim ~/.local/bin/familia; scripts/install-cli.sh)
Example: curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install.sh | sh -s -- --yes --no-start
USAGE
  exit 0 ;; esac

PREFIX=${INSTALL_PREFIX:-$HOME/familia}
REPO_URL=${FAMILIA_REPO_URL:-${FEELD_REPO_URL:-https://github.com/brianreborn/familia.git}}  # FEELD_REPO_URL is a deprecated alias

die() { echo "install.sh: $*" >&2; exit 1; }

DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --yes|-y) INSTALL_ACK=yes; FAMILIA_ACCEPT_LICENSES=yes; export INSTALL_ACK FAMILIA_ACCEPT_LICENSES ;;
    --accept-unknown) FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes; export FAMILIA_ACCEPT_UNKNOWN_LICENSES ;;
    --no-start) INSTALL_NO_START=1 ;;
    --no-path) INSTALL_NO_PATH=1 ;;
    *) die "unknown option '$1'. Try: sh install.sh --help" ;;
  esac
  shift
done
if [ "$DRY" = 1 ]; then
  echo "install.sh: [dry-run] would clone or update $REPO_URL in $PREFIX" >&2
  echo "install.sh: [dry-run] would show the license review (scripts/licenses.py gate)" >&2
  echo "install.sh: [dry-run] would run sh $PREFIX/scripts/configure.sh (fetches the pins in pins.txt)" >&2
  [ "${INSTALL_NO_PATH:-0}" = 1 ] || echo "install.sh: [dry-run] would put familia on PATH: sh $PREFIX/scripts/install-cli.sh" >&2
  [ "${INSTALL_NO_START:-0}" = 1 ] || echo "install.sh: [dry-run] would start: sh $PREFIX/start.sh" >&2
  exit 0
fi

command -v git >/dev/null 2>&1 || die "git is required. Install it (Debian/Ubuntu: sudo apt install git; Termux: pkg install git), then run this again."

# The second click. Paying is not required. The notice is not optional.
# INSTALL_ACK=yes is the non-interactive answer.
ack_notice() {
  case "${INSTALL_ACK:-}" in
    yes) return 0 ;;
    no) die "not acknowledged" ;;
  esac
  echo "install.sh: This product includes software developed by Brian Fundakowski Feldman." >&2
  echo "install.sh: If this is useful, a contribution toward rent, groceries, or keeping the lights on is welcome. It is an invitation, not a requirement." >&2
  if [ ! -r /dev/tty ]; then
    die "type yes on a terminal, or set INSTALL_ACK=yes"
  fi
  printf 'install.sh: type yes to continue: ' >&2
  read -r ans < /dev/tty || die "no acknowledgement"
  case "$ans" in
    yes|y) ;;
    *) die "not acknowledged" ;;
  esac
}
ack_notice

if [ ! -d "$PREFIX/.git" ]; then
  echo "install.sh: checking out FAMILIA into $PREFIX..." >&2
  git clone "$REPO_URL" "$PREFIX"
else
  echo "install.sh: updating FAMILIA at $PREFIX..." >&2
  git -C "$PREFIX" pull origin main || true
fi

# Licenses before anything is fetched or run (docs/licenses.md).
command -v python3 >/dev/null 2>&1 || die "python3 is required (Debian/Ubuntu: sudo apt install python3; Termux: pkg install python)."
python3 "$PREFIX/scripts/licenses.py" gate || die "licenses not accepted; stopped before fetching anything. Review: python3 $PREFIX/scripts/licenses.py review (or re-run with --yes, plus --accept-unknown for unknown licenses)"

# Run configuration shell
echo "install.sh: running configuration shell..." >&2
sh "$PREFIX/scripts/configure.sh"
if [ "${INSTALL_NO_PATH:-0}" != 1 ] && [ -f "$PREFIX/scripts/install-cli.sh" ]; then
  sh "$PREFIX/scripts/install-cli.sh" >&2 || echo "install.sh: warning: could not put familia on PATH" >&2
fi

echo "install.sh: next steps: cd $PREFIX && ./familia   (opens the menu; start with Skills, then Agents)" >&2
if [ "${INSTALL_NO_START:-0}" = "1" ]; then
  echo "install.sh: installation complete (not starting; you asked for --no-start)." >&2
else
  echo "install.sh: starting FAMILIA..." >&2
  exec sh "$PREFIX/start.sh"
fi
