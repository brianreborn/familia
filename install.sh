#!/bin/sh
# FAMILIA: Top-level super-project installer.
# Pure POSIX /bin/sh.
# Two clicks:
#   p=familia                          && \
#   o=brianreborn                      && \
#   h=raw.githubusercontent.com        && \
#   u=https://$h/$o/$p/main/install.sh && \
#   curl -fsSLo install-$p.sh $u       && \
#   sh        ./install-$p.sh
# Click 1 is running the command. Click 2 is the donation tap-through.
set -eu
case "${1:-}" in -h|--help) cat <<'USAGE'
install.sh: Install familia into ~/familia (or $INSTALL_PREFIX), sync the pinned parts, then start it.
Usage:
  sh install.sh [--dry-run] [--yes] [--no-start] [--no-path] [--branch BRANCH]
    --dry-run   say what would happen; change nothing
    --auto-deps install missing OS packages after one confirmation (AUTO_DEPS=1); without it the exact command is printed
    --yes       non-interactive: acknowledge the notice and accept licenses (the summary is still printed)
    --no-start  stop after setup (same as INSTALL_NO_START=1)
    --no-path   do not put `familia` on PATH (default: 2-line shim ~/.local/bin/familia; scripts/install-cli.sh)
    --branch    choose a branch for a new checkout or switch an existing checkout to track it
Preliminary stock (owned by this script): OS packages via install/deps.sh when anything
base is missing, and Charm gum into ~/.local/bin via scripts/install-gum.sh (no sudo; soft-fail).
llama.cpp is prebuilt-first: an existing build is reused, else the sha256-checked b11944 release
binary for this OS/arch; it builds from source only when none fits (FreeBSD, Termux) or BUILD=1.
Example:
  p=familia                          && \
  o=brianreborn                      && \
  h=raw.githubusercontent.com        && \
  u=https://$h/$o/$p/main/install.sh && \
  curl -fsSLo install-$p.sh $u       && \
  sh        ./install-$p.sh --yes --no-start
USAGE
  exit 0 ;; esac

PREFIX=${INSTALL_PREFIX:-$HOME/familia}
REPO_URL=${FAMILIA_REPO_URL:-${FEELD_REPO_URL:-https://github.com/brianreborn/familia.git}}  # FEELD_REPO_URL is a deprecated alias

die() { echo "install.sh: $*" >&2; exit 1; }

DRY=0
BRANCH=${FAMILIA_BRANCH:-}
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --branch) [ $# -ge 2 ] || die "--branch needs a branch name"; shift; BRANCH=$1 ;;
    --yes|-y) INSTALL_ACK=yes; FAMILIA_ACCEPT_LICENSES=yes; export INSTALL_ACK FAMILIA_ACCEPT_LICENSES ;;
    --auto-deps) AUTO_DEPS=1; export AUTO_DEPS ;;
    --accept-unknown) FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes; export FAMILIA_ACCEPT_UNKNOWN_LICENSES ;;
    --no-start) INSTALL_NO_START=1 ;;
    --no-path) INSTALL_NO_PATH=1 ;;
    *) die "unknown option '$1'. Try: sh install.sh --help" ;;
  esac
  shift
done
if [ "$DRY" = 1 ]; then
  echo "install.sh: [dry-run] would clone or update $REPO_URL in $PREFIX${BRANCH:+ on branch $BRANCH}" >&2
  echo "install.sh: [dry-run] would install preliminary stock if missing: sh $PREFIX/install/deps.sh --install (git/curl/python3/…)" >&2
  echo "install.sh: [dry-run] would ensure Charm gum in ~/.local/bin: sh $PREFIX/scripts/install-gum.sh --dry-run" >&2
  echo "install.sh: [dry-run] would show the license review (scripts/licenses.py gate)" >&2
  echo "install.sh: [dry-run] would run sh $PREFIX/scripts/configure.sh (syncs every pin in pins.txt together; scripts/sync_pins.py)" >&2
  [ "${INSTALL_NO_PATH:-0}" = 1 ] || echo "install.sh: [dry-run] would put familia on PATH: sh $PREFIX/scripts/install-cli.sh" >&2
  [ "${INSTALL_NO_START:-0}" = 1 ] || echo "install.sh: [dry-run] would start: sh $PREFIX/start.sh" >&2
  exit 0
fi

command -v git >/dev/null 2>&1 || die "git is required. Install it then re-run (Linux: sudo apt install git; Termux: pkg install git; after checkout: sh install/deps.sh --install). See docs/safe-mode-bootstrap.md."
if [ -n "$BRANCH" ]; then
  git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || die "invalid branch name: $BRANCH"
fi

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
  if [ -n "$BRANCH" ]; then git clone --branch "$BRANCH" "$REPO_URL" "$PREFIX"
  else git clone "$REPO_URL" "$PREFIX"; fi
else
  echo "install.sh: updating FAMILIA at $PREFIX..." >&2
  if [ -n "$BRANCH" ]; then
    git -C "$PREFIX" fetch origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" ||
      die "could not fetch origin/$BRANCH"
    if git -C "$PREFIX" show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git -C "$PREFIX" switch "$BRANCH" || die "could not switch to $BRANCH; check for local changes"
    else
      git -C "$PREFIX" switch --track -c "$BRANCH" "origin/$BRANCH" ||
        die "could not switch to $BRANCH; check for local changes"
    fi
    git -C "$PREFIX" branch --set-upstream-to="origin/$BRANCH" "$BRANCH" ||
      die "could not set $BRANCH to track origin/$BRANCH"
    git -C "$PREFIX" merge --ff-only --autostash "origin/$BRANCH" ||
      die "could not fast-forward $BRANCH; local changes were preserved"
  else
    git -C "$PREFIX" pull --ff-only --autostash ||
      die "could not fast-forward the current branch from its configured upstream; local changes were preserved"
  fi
fi

# Preliminary stock (owned here — small and trivial): OS packages + Charm gum.
# install/deps.sh and scripts/install-gum.sh are the helpers; this script triggers them
# whenever anything in the base stock is missing (not only python3/curl).
# Home of the build-helper AI: pinned code-bootstraps-llama.cpp.
if [ -f "$PREFIX/install/deps.sh" ]; then
  if sh "$PREFIX/install/deps.sh" >/dev/null 2>&1; then
    echo "install.sh: preliminary OS packages look present" >&2
  else
    echo "install.sh: preliminary OS packages missing" >&2
    if [ "${AUTO_DEPS:-0}" != 1 ]; then
      # No root without an explicit --auto-deps: print the packages and the command only.
      sh "$PREFIX/install/deps.sh" || true
      if ! python3 -c 'import yaml' >/dev/null 2>&1; then
        echo "install.sh: trying PyYAML without root: python3 -m pip install --user pyyaml" >&2
        python3 -m pip install --user --quiet pyyaml >/dev/null 2>&1 \
          || python3 -m pip install --user --break-system-packages --quiet pyyaml >/dev/null 2>&1 || true
      fi
      if sh "$PREFIX/install/deps.sh" >/dev/null 2>&1; then
        echo "install.sh: preliminary packages satisfied without root" >&2
      else
        die "install the packages with the command above, or re-run with --auto-deps (or AUTO_DEPS=1) to install them (needs root)"
      fi
    else
      echo "install.sh: WARNING: the next step installs OS packages AS ROOT (sudo / package manager)." >&2
      if [ "${INSTALL_ACK:-}" = yes ]; then
        sh "$PREFIX/install/deps.sh" --install --yes || die "deps install failed; see docs/safe-mode-bootstrap.md"
      else
        sh "$PREFIX/install/deps.sh" --install || die "deps install failed or declined; see: sh $PREFIX/install/deps.sh --help"
      fi
    fi
  fi
fi
# Charm gum → ~/.local/bin (no sudo). Soft-fail: home falls back to ./familia --legacy-menu.
if [ -f "$PREFIX/scripts/install-gum.sh" ]; then
  echo "install.sh: ensuring Charm gum in ~/.local/bin…" >&2
  GUM_FLAGS=""
  if [ "${INSTALL_ACK:-}" = yes ] || [ "${FAMILIA_ACCEPT_LICENSES:-}" = yes ]; then
    GUM_FLAGS="--yes"
  fi
  # shellcheck disable=SC2086
  if ! sh "$PREFIX/scripts/install-gum.sh" $GUM_FLAGS; then
    echo "install.sh: warning: gum not installed; ./familia home needs it. Retry: sh $PREFIX/scripts/install-gum.sh" >&2
    echo "install.sh: legacy menu without gum: cd $PREFIX && ./familia --legacy-menu" >&2
  fi
fi

# Licenses before anything is fetched or run (docs/licenses.md).
command -v python3 >/dev/null 2>&1 || die "python3 is required (Debian/Ubuntu: sudo apt install python3; Termux: pkg install python; or: sh $PREFIX/install/deps.sh --install)."
[ "${INSTALL_ACK:-}" = yes ] && { FAMILIA_ACCEPT_LICENSES=yes; export FAMILIA_ACCEPT_LICENSES; }
python3 "$PREFIX/scripts/licenses.py" gate || die "licenses not accepted; stopped before fetching anything. Review: python3 $PREFIX/scripts/licenses.py review (or re-run with --yes, plus --accept-unknown for unknown licenses)"
# Accepted once for this run: start.sh and anything it runs reuse that answer (the summary
# is still printed if the selection grows after the pinned parts are fetched).
FAMILIA_ACCEPT_LICENSES=yes; FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes; export FAMILIA_ACCEPT_LICENSES FAMILIA_ACCEPT_UNKNOWN_LICENSES

# Run configuration shell (syncs every pin in pins.txt together).
# A leftover empty gitlink dir for a pin (from an old .gitmodules) used to stop
# here with a refuse; sync_pins.py now replaces empty placeholders automatically.
echo "install.sh: running configuration shell..." >&2
if ! sh "$PREFIX/scripts/configure.sh"; then
  echo "install.sh: configuration failed (pinned parts could not be synced)." >&2
  echo "install.sh: common fix: if a pin directory exists but is empty / not a git checkout," >&2
  echo "install.sh:   mv $PREFIX/<name> $PREFIX/<name>.bak && sh $PREFIX/scripts/configure.sh" >&2
  echo "install.sh: or: cd $PREFIX && ./familia sync --dry-run   # see what is refused" >&2
  echo "install.sh: pins are NOT git submodules (see pins.txt). Do not run git submodule update." >&2
  die "configure.sh failed"
fi
if [ "${INSTALL_NO_PATH:-0}" != 1 ] && [ -f "$PREFIX/scripts/install-cli.sh" ]; then
  sh "$PREFIX/scripts/install-cli.sh" >&2 || echo "install.sh: warning: could not put familia on PATH" >&2
fi

echo "install.sh: next steps: cd $PREFIX && ./familia   (Charm/gum home — Talk to the protomodel first; legacy: ./familia --legacy-menu)" >&2
if [ "${INSTALL_NO_START:-0}" = "1" ]; then
  echo "install.sh: installation complete (not starting; you asked for --no-start)." >&2
else
  echo "install.sh: starting FAMILIA..." >&2
  exec sh "$PREFIX/start.sh"
fi
