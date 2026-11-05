#!/bin/sh
# familia installer: FreeBSD (user scope, POSIX sh, no bash, no GNU-only flags).
# This file is the single download. Verify it BEFORE running it:
#   fetch -o install-familia.sh URL      (or: curl -fsSLo install-familia.sh URL)
#   sha256 -q install-familia.sh         (compare with the published SHA256)
#   sh ./install-familia.sh [flags]
# Flags: --prefix DIR   install root (default ~/.local/share/familia)
#        --auto-deps    allow `pkg install` via sudo/doas for missing packages
#                       (asks first; never silent, never without this flag)
#        --yes          non-interactive: accept defaults (does NOT imply --auto-deps)
#        --dry-run      print every action, change nothing; exit 1 if the
#                       node could not start (missing deps)
#        --uninstall    remove repo + launcher (keeps models and api.key)
#        -h, --help     this text
# Env:   FAMILIA_REPO_URL  clone source (default github.com/brianreborn/familia)
#        The clone is checked out at the pinned FAMILIA_REF below and verified.
# Security: llama-server binds loopback only; an API key (0600,
# ~/.config/familia/api.key) is required on every bind, loopback included;
# FAMILIA_EXTRA / argv tokens that override host/port/key/TLS/path are refused.
set -eu

PREFIX=${FAMILIA_PREFIX:-$HOME/.local/share/familia}
BIN_DIR=${FAMILIA_BIN_DIR:-$HOME/.local/bin}
REPO_URL=${FAMILIA_REPO_URL:-https://github.com/brianreborn/familia.git}
# Pinned familia release commit; bump together with this file's published SHA256.
FAMILIA_REF=3741a2ed39ccc5b7251fd7f25c37b0d353be0092
REF=$FAMILIA_REF
# Pinned llama.cpp (familia v0.2): tag b11969, built from source (no FreeBSD prebuilt).
LLAMA_TAG=b11969
LLAMA_SHA=c3df4b7e22a1ac38da663552d19e649dd97ca936
LLAMA_URL=${FAMILIA_LLAMA_URL:-https://github.com/ggml-org/llama.cpp.git}
DRY=0; AUTO_DEPS=0; YES=0; UNINSTALL=0
KEY="$HOME/.config/familia/api.key"

say() { printf 'familia-install: %s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }
run() { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }
have() { command -v "$1" >/dev/null 2>&1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) shift; [ -n "${1:-}" ] || die "--prefix needs a directory"; PREFIX=$1 ;;
    --auto-deps) AUTO_DEPS=1 ;;
    --yes|-y) YES=1 ;;
    --dry-run|-n) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
  shift
done
# L1: FAMILIA_REF_OVERRIDE (40-hex sha) only with --dry-run or FAMILIA_TEST_MODE=1.
if [ -n "${FAMILIA_REF_OVERRIDE:-}" ]; then
  [ "$DRY" = 1 ] || [ "${FAMILIA_TEST_MODE:-}" = 1 ] ||
    die "FAMILIA_REF_OVERRIDE is test-only (needs --dry-run or FAMILIA_TEST_MODE=1); refusing"
  REF=$FAMILIA_REF_OVERRIDE; say "warning: using FAMILIA_REF_OVERRIDE $REF (not the pinned release)"
fi
case "$REF" in *[!0-9a-f]*) die "FAMILIA_REF must be a 40-hex sha" ;; esac
[ ${#REF} -eq 40 ] || die "FAMILIA_REF must be a 40-hex sha"
# B1: paths are baked into the generated launcher; allow only a safe charset.
check_path() {
  case "$2" in /*) ;; *) die "$1 must be absolute: $2" ;; esac
  case "$2" in *[!A-Za-z0-9._/-]*) die "$1 has characters outside [A-Za-z0-9._/-]: $2" ;; esac
  case "/$2/" in */../*) die "$1 must not contain ..: $2" ;; esac
}
check_path --prefix "$PREFIX"; check_path FAMILIA_BIN_DIR "$BIN_DIR"

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
PY=""; for c in python3 python3.11; do have "$c" && { PY=$c; break; }; done
have git || missing="$missing git"
[ -n "$PY" ] || missing="$missing python3"
RT="$PREFIX/runtime/$LLAMA_TAG"; LS="$RT/llama-server"
# L2: reuse a build only if .built-sha matches the pin and --version names b11969/c3df4b7.
llama_ok() {
  [ -x "$LS" ] && [ "$(cat "$RT/.built-sha" 2>/dev/null)" = "$LLAMA_SHA" ] &&
    "$LS" --version 2>&1 | grep -Eq "${LLAMA_TAG#b}|$(printf %.7s "$LLAMA_SHA")"
}
if ! llama_ok; then have cmake || missing="$missing cmake"; have c++ || missing="$missing llvm"; fi
PYV=311; [ -n "$PY" ] && PYV=$("$PY" -c 'import sys; print("%d%d" % sys.version_info[:2])')
{ [ -n "$PY" ] && "$PY" -c 'import yaml' >/dev/null 2>&1; } || missing="$missing py$PYV-pyyaml"
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
  [ -z "$ans" ] || PREFIX=$ans
  check_path "install directory" "$PREFIX"
fi
run mkdir -p "$PREFIX/models" "$BIN_DIR"
[ -d "$PREFIX/repo/.git" ] || run git clone -q --no-checkout "$REPO_URL" "$PREFIX/repo"
run git -C "$PREFIX/repo" fetch -q origin "$REF" 2>/dev/null || run git -C "$PREFIX/repo" fetch -q origin
run git -C "$PREFIX/repo" -c advice.detachedHead=false checkout -q --detach "$REF" || die "could not check out pinned $REF"
if [ "$DRY" != 1 ]; then
  GOT=$(git -C "$PREFIX/repo" rev-parse HEAD)
  [ "$GOT" = "$REF" ] || die "repo HEAD $GOT is not the pinned $REF"
  say "familia pinned at $REF"
fi

# 2b. llama.cpp $LLAMA_TAG from source at the pinned sha (reused if already built).
if llama_ok; then say "llama-server $LLAMA_TAG already built and verified: $LS"
elif [ "$DRY" = 1 ]; then say "[dry-run] build llama.cpp $LLAMA_TAG ($LLAMA_SHA) into $RT"
else
  SRC="$RT/src"; mkdir -p "$RT"
  [ -d "$SRC/.git" ] || git clone -q --no-checkout "$LLAMA_URL" "$SRC" || die "llama.cpp clone failed"
  git -C "$SRC" fetch -q --depth 1 origin "$LLAMA_SHA" 2>/dev/null || git -C "$SRC" fetch -q origin
  git -C "$SRC" -c advice.detachedHead=false checkout -q --detach "$LLAMA_SHA" || die "could not check out llama.cpp $LLAMA_SHA"
  [ "$(git -C "$SRC" rev-parse HEAD)" = "$LLAMA_SHA" ] || die "llama.cpp HEAD is not pinned $LLAMA_SHA"
  J=$(getconf NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)
  cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DGGML_NATIVE=OFF >&2 || die "cmake configure failed"
  cmake --build "$SRC/build" --target llama-server -j "$J" >&2 || die "llama.cpp build failed"
  { cp "$SRC/build/bin/llama-server" "$LS.tmp.$$" && mv "$LS.tmp.$$" "$LS"; } || die "could not install $LS"
  printf '%s\n' "$LLAMA_SHA" > "$RT/.built-sha"
  llama_ok || die "built llama-server does not report $LLAMA_TAG"
fi
if [ "$DRY" != 1 ]; then
  "$LS" --help 2>&1 | grep -q -- '--api-key-file' || die "$LS lacks --api-key-file; refusing"
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
# N-a: UTF-8 ctype when the locale is unset or C/POSIX.
case "\${LC_ALL:-\${LC_CTYPE:-\${LANG:-}}}" in ""|C|POSIX) LC_CTYPE=C.UTF-8; export LC_CTYPE ;; esac
case "\${LANG:-}" in ""|C|POSIX) LANG=C.UTF-8; export LANG ;; esac
case "\${LC_ALL:-}" in C|POSIX) unset LC_ALL ;; esac
# B3 (mandatory): llama-server reads LLAMA_ARG_* (e.g. SSL, STATIC_PATH, HOST) from the
# environment, which would bypass the F-6 argv check; scrub them all.
unset LLAMA_API_KEY
for _v in \$(env | sed -n 's/^\\(LLAMA_ARG_[A-Za-z0-9_]*\\)=.*/\\1/p'); do unset "\$_v"; done
: "\${FAMILIA_MODEL:?set FAMILIA_MODEL to a GGUF path or a name in $PREFIX/models}"
M="\$FAMILIA_MODEL"
# B4: a bare name under models/, or an absolute existing file; never "..".
case "/\$M/" in */../*) echo "familia-start: FAMILIA_MODEL must not contain .." >&2; exit 2 ;; esac
case "\$M" in
  /*) [ -f "\$M" ] || { echo "familia-start: model \$M not found" >&2; exit 2; } ;;
  */*) echo "familia-start: FAMILIA_MODEL must be a bare name or an absolute path" >&2; exit 2 ;;
  *) M="$PREFIX/models/\$M" ;;
esac
B="$LS"; [ -x "\$B" ] || { echo "familia-start: \$B missing; re-run install-familia.sh" >&2; exit 2; }
"\$B" --help 2>&1 | grep -q -- '--api-key-file' || { echo "familia-start: \$B lacks --api-key-file; refusing" >&2; exit 2; }
# F-6: refuse (never strip) any FAMILIA_EXTRA or argv token overriding bind/port/auth/TLS/path.
# set -f stays on: FAMILIA_EXTRA is expanded unquoted below and must not glob.
set -f
for _t in \${FAMILIA_EXTRA:-} "\$@"; do
  case "\$_t" in
    --host*|--port*|--api-key*|--ssl*|--path*) echo "familia-start: token \$_t would override bind/port/auth/TLS/path; refusing" >&2; exit 2 ;;
  esac
done
H="\${FAMILIA_BIND:-127.0.0.1}"; [ "\$H" = '[::1]' ] && H=::1; [ "\$H" = localhost ] && H=127.0.0.1
case "\$H" in 127.0.0.1|::1) ;; *) echo "familia-start: non-loopback bind \$H refused by this installer" >&2; exit 2 ;; esac
KF="\${FAMILIA_API_KEY_FILE:-\$HOME/.config/familia/api.key}"
[ -f "\$KF" ] && [ ! -L "\$KF" ] || { echo "familia-start: key file \$KF missing or a symlink; a key is required on every bind" >&2; exit 2; }
if [ "\$(uname -s)" = FreeBSD ]; then KM=\$(stat -f %Lp "\$KF"); else KM=\$(stat -c %a "\$KF"); fi
if [ "\$(uname -s)" = FreeBSD ]; then KU=\$(stat -f %u "\$KF"); else KU=\$(stat -c %u "\$KF"); fi
[ "\$KU" = "\$(id -u)" ] || { echo "familia-start: \$KF is not owned by you" >&2; exit 2; }
case "\$KM" in 600|400) ;; *) echo "familia-start: \$KF must be mode 0600" >&2; exit 2 ;; esac
exec "\$B" -m "\$M" --host "\$H" --port "\${FAMILIA_PORT:-9941}" --api-key-file "\$KF" -c "\${FAMILIA_CTX:-4096}" \${FAMILIA_EXTRA:-} "\$@"
EOS
  chmod 0755 "$LAUNCH.tmp.$$" && mv "$LAUNCH.tmp.$$" "$LAUNCH"
fi
say "done. Put models in $PREFIX/models; start: FAMILIA_MODEL=x.gguf $LAUNCH"
say "autostart (optional, rootless): crontab -e, add: @reboot FAMILIA_MODEL=x.gguf $LAUNCH"
