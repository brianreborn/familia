#!/bin/sh
# familia installer: FreeBSD (user scope, POSIX sh, no bash, no GNU-only flags).
# This file is the single download. Verify it BEFORE running it:
#   fetch -o install-familia.sh URL      (or: curl -fsSLo install-familia.sh URL)
#   sha256 -q install-familia.sh         (compare with the published SHA256)
#   sh ./install-familia.sh [flags]
# Flags: --prefix DIR   install root (default ~/.local/share/familia)
#        --branch REF   familia branch or tag to clone (default main)
#        --auto-deps    allow `pkg install` via sudo/doas for missing packages
#                       (asks first; never silent, never without this flag)
#        --yes          non-interactive: accept defaults (does NOT imply --auto-deps)
#        --dry-run      print every action, change nothing; exit 1 if the
#                       node could not start (missing deps)
#        --uninstall    remove repo + launcher (keeps models and api.key)
#        -h, --help     this text
# Env:   FAMILIA_REPO_URL  clone source (default github.com/brianreborn/familia)
# Security: llama-server binds loopback only; an API key (0600,
# ~/.config/familia/api.key) is required on every bind, loopback included;
# FAMILIA_EXTRA / argv tokens that override host/port/key/TLS/path are refused.
set -eu

PREFIX=${FAMILIA_PREFIX:-$HOME/.local/share/familia}
BIN_DIR=${FAMILIA_BIN_DIR:-$HOME/.local/bin}
REPO_URL=${FAMILIA_REPO_URL:-https://github.com/brianreborn/familia.git}
BRANCH=main; DRY=0; AUTO_DEPS=0; YES=0; UNINSTALL=0
KEY="$HOME/.config/familia/api.key"

say() { printf 'familia-install: %s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }
run() { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }
have() { command -v "$1" >/dev/null 2>&1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) shift; [ -n "${1:-}" ] || die "--prefix needs a directory"; PREFIX=$1 ;;
    --branch) shift; [ -n "${1:-}" ] || die "--branch needs a name"; BRANCH=$1 ;;
    --auto-deps) AUTO_DEPS=1 ;;
    --yes|-y) YES=1 ;;
    --dry-run|-n) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
  shift
done
case "$BRANCH" in -*|*..*|*' '*) die "invalid branch: $BRANCH" ;; esac
case "$PREFIX" in /*) ;; *) die "--prefix must be absolute: $PREFIX" ;; esac

OS=$(uname -s)
if [ "$OS" != FreeBSD ]; then
  [ "${FAMILIA_ALLOW_NON_FREEBSD:-}" = yes ] || [ "$DRY" = 1 ] ||
    die "this installer is for FreeBSD (got $OS); use install/linux/install.sh"
  say "note: $OS is not FreeBSD; continuing (dry-run/test mode)"
fi
[ "$(id -u)" != 0 ] || die "do not run as root; this is a user-scope installer (use --auto-deps for pkg)"

LAUNCH="$BIN_DIR/familia-start"
if [ "$UNINSTALL" = 1 ]; then
  run rm -f "$LAUNCH"
  run rm -rf "$PREFIX/repo"
  say "uninstalled; kept $PREFIX/models and $KEY"; exit 0
fi

# 1. prerequisites (pkg). Map: command -> package.
missing=""
for pair in git:git python3:python3 llama-server:llama-cpp; do
  have "${pair%%:*}" || missing="$missing ${pair#*:}"
done
python3 -c 'import yaml' >/dev/null 2>&1 || missing="$missing py311-pyyaml"
missing=${missing# }
if [ -n "$missing" ]; then
  say "missing dependencies: $missing"
  say "install them with: pkg install -y $missing   (as root)"
  if [ "$AUTO_DEPS" != 1 ]; then
    [ "$DRY" = 1 ] && { say "[dry-run] would halt here: missing dependencies"; exit 1; }
    die "missing dependencies; install them, or re-run with --auto-deps"
  fi
  ESC=""
  if have doas; then ESC=doas; elif have sudo; then ESC=sudo; fi
  [ -n "$ESC" ] || die "--auto-deps needs sudo or doas; install packages as root yourself"
  say "WARNING: about to run as root: $ESC pkg install -y $missing"
  [ "$DRY" = 1 ] && { say "[dry-run] would ask, then run: $ESC pkg install -y $missing"; exit 1; }
  [ -t 0 ] || die "--auto-deps needs a terminal to confirm the root step"
  printf 'Type yes to run "%s pkg install -y %s": ' "$ESC" "$missing" >&2
  ans=""; read -r ans || ans=""
  [ "$ans" = yes ] || die "not confirmed; nothing was changed"
  # shellcheck disable=SC2086
  "$ESC" pkg install -y $missing || die "pkg install failed"
fi

# 2. install root and repo
if [ "$YES" != 1 ] && [ "$DRY" != 1 ] && [ -t 0 ]; then
  printf 'Install directory [%s]: ' "$PREFIX" >&2
  ans=""; read -r ans || ans=""
  case "$ans" in "") ;; /*) PREFIX=$ans ;; *) die "directory must be absolute" ;; esac
fi
run mkdir -p "$PREFIX/models" "$BIN_DIR"
if [ -d "$PREFIX/repo/.git" ]; then
  run git -C "$PREFIX/repo" pull --ff-only -q || say "warning: repo not fast-forwardable; left as is"
else
  run git clone -q --branch "$BRANCH" "$REPO_URL" "$PREFIX/repo"
fi

# 3. API key: required on every bind (Brian 2026-11-02). 0600, never overwritten.
if [ -e "$KEY" ] || [ -L "$KEY" ]; then say "API key exists: $KEY"
elif [ "$DRY" = 1 ]; then say "[dry-run] generate $KEY (0600)"
else
  ( umask 077; mkdir -p "${KEY%/*}" &&
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n' > "$KEY.tmp.$$" &&
    mv "$KEY.tmp.$$" "$KEY" ) || { rm -f "$KEY.tmp.$$"; die "could not write $KEY"; }
  say "generated API key $KEY (0600); clients send Authorization: Bearer <key>"
fi

# 4. launcher (loopback bind, key required, F-6 override refusal)
if [ "$DRY" = 1 ]; then say "[dry-run] write $LAUNCH"
else
  cat > "$LAUNCH.tmp.$$" <<EOS
#!/bin/sh
# generated by familia install/freebsd/install-familia.sh
set -eu
: "\${FAMILIA_MODEL:?set FAMILIA_MODEL to a GGUF path or a name in $PREFIX/models}"
M="\$FAMILIA_MODEL"; [ -f "\$M" ] || M="$PREFIX/models/\$FAMILIA_MODEL"
B=\$(command -v llama-server) || { echo "familia-start: llama-server not found (pkg install llama-cpp)" >&2; exit 2; }
# F-6: refuse (never strip) any FAMILIA_EXTRA or argv token overriding bind/port/auth/TLS/path.
# set -f stays on: FAMILIA_EXTRA is expanded unquoted below and must not glob.
set -f
for _t in \${FAMILIA_EXTRA:-} "\$@"; do
  case "\$_t" in
    --host*|--port*|--api-key*|--ssl*|--path*) echo "familia-start: token \$_t would override bind/port/auth/TLS/path; refusing" >&2; exit 2 ;;
  esac
done
H="\${FAMILIA_BIND:-127.0.0.1}"; [ "\$H" = '[::1]' ] && H=::1
case "\$H" in 127.0.0.1|::1|localhost) ;; *) echo "familia-start: non-loopback bind \$H refused by this installer" >&2; exit 2 ;; esac
KF="\${FAMILIA_API_KEY_FILE:-\$HOME/.config/familia/api.key}"
[ -f "\$KF" ] && [ ! -L "\$KF" ] || { echo "familia-start: key file \$KF missing or a symlink; a key is required on every bind" >&2; exit 2; }
if [ "\$(uname -s)" = FreeBSD ]; then KM=\$(stat -f %Lp "\$KF"); else KM=\$(stat -c %a "\$KF"); fi
case "\$KM" in 600|400) ;; *) echo "familia-start: \$KF must be mode 0600" >&2; exit 2 ;; esac
exec "\$B" -m "\$M" --host "\$H" --port "\${FAMILIA_PORT:-9941}" --api-key-file "\$KF" -c "\${FAMILIA_CTX:-4096}" \${FAMILIA_EXTRA:-} "\$@"
EOS
  chmod 0755 "$LAUNCH.tmp.$$" && mv "$LAUNCH.tmp.$$" "$LAUNCH"
fi
say "done. Put models in $PREFIX/models; start: FAMILIA_MODEL=x.gguf $LAUNCH"
say "autostart (optional, rootless): crontab -e, add: @reboot FAMILIA_MODEL=x.gguf $LAUNCH"
