#!/bin/sh
# FAMILIA: Top-level super-project installer.
# Pure POSIX /bin/sh.
# Two clicks:
#   curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install.sh | sh
# Click 1 is running the command. Click 2 is the donation tap-through.
set -eu

PREFIX=${INSTALL_PREFIX:-$HOME/familia}
REPO_URL=${FAMILIA_REPO_URL:-${FEELD_REPO_URL:-https://github.com/brianreborn/familia.git}}  # FEELD_REPO_URL is a deprecated alias

die() { echo "install.sh: $*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "git is required"

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

# Run configuration shell
echo "install.sh: running configuration shell..." >&2
sh "$PREFIX/scripts/configure.sh"

if [ "${INSTALL_NO_START:-0}" = "1" ]; then
  echo "install.sh: installation complete (INSTALL_NO_START=1, skipping start.sh)." >&2
else
  echo "install.sh: starting FAMILIA..." >&2
  exec sh "$PREFIX/start.sh"
fi
