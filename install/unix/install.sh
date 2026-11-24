#!/bin/sh
# familia unified installer: Linux, FreeBSD, macOS (Darwin), Android (Termux).
# Standard Base Prefix Layout: ~/brianreborn/familia-0.3.0 (symlink ~/brianreborn/familia)
# Usage: sh install/unix/install.sh [flags]
# Flags:
#   --prefix DIR       install root (default: ~/brianreborn/familia-0.3.0, or $INSTALL_PREFIX)
#   --dry-run, -n      print every action, change nothing
#   --yes, -y          accept license review without prompt; attests root; acknowledges contribution
#   --accept-unknown   also accept components whose license could not be found
#   --allow-root       attest running as root
#   --auto-deps        install missing OS packages after confirmation (AUTO_DEPS=1)
#   --uninstall        remove installed files (models kept unless --purge)
#   --purge            with --uninstall: also remove models
#   --name NAME        host name for graph.yaml (default: short hostname)
#   --branch BRANCH    familia branch (default: current checkout branch, else main)
#   --build bNNNN      llama.cpp release tag (Linux/macOS pre-built; default b11539)
#   --no-runtime       skip llama.cpp download/build
#   --no-start         stop after setup; do not auto-start familia-start
#   --no-pgo           skip Python PGO compilation offer
#   --no-hermes        skip Hermes agent installation
#   --no-path          skip putting familia on PATH
#   --systemd          install systemd --user unit (Linux)
#   --no-wakelock      skip termux-wake-lock (Termux)
#   --sshd             install+start openssh key-auth (Termux)
#   --channel CH       release channel: bleeding|stable (default bleeding)
#   --stable-days N    stable channel soak days, 1..365 (default 30)
#   --force-host       replace existing host entry in graph.yaml
#
# No sudo/root required. User-space prefix layout in compliance with Unix FHS.
set -eu

umask 077

VERSION="0.3.0"
DEFAULT_PREFIX="$HOME/brianreborn/familia-$VERSION"
SYMLINK_PREFIX="$HOME/brianreborn/familia"

# Prefix: accept $INSTALL_PREFIX or $FAMILIA_PREFIX or default
PREFIX=${INSTALL_PREFIX:-${FAMILIA_PREFIX:-$DEFAULT_PREFIX}}
REPO_URL=${FAMILIA_REPO_URL:-${FEELD_REPO_URL:-https://github.com/brianreborn/familia.git}}
SOURCE_BRANCH=""
if [ -f "$0" ]; then
  SOURCE_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." 2>/dev/null && pwd || true)
  if [ -n "$SOURCE_ROOT" ] && git -C "$SOURCE_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    SOURCE_BRANCH=$(git -C "$SOURCE_ROOT" branch --show-current 2>/dev/null || true)
  fi
fi
BRANCH=${FAMILIA_BRANCH:-${SOURCE_BRANCH:-}}
SELECT_BRANCH=0
{ [ -n "${FAMILIA_BRANCH:-}" ] || [ -n "$SOURCE_BRANCH" ]; } && SELECT_BRANCH=1
export SELECT_BRANCH

API=${FAMILIA_LLAMA_API:-https://api.github.com/repos/ggml-org/llama.cpp/releases}
DRY=0; UNINSTALL=0; PURGE=0; NAME=""; BUILD=${FAMILIA_LLAMA_BUILD:-b11539}
RUNTIME=1; PGO=1; HERMES=1; SYSTEMD=0; FORCE_HOST=""; NOPATH=0; WAKELOCK=1; SSHD=0; NO_START=0
AUTO_DEPS=${AUTO_DEPS:-0}
BUILD_SET=0; [ -n "${FAMILIA_LLAMA_BUILD:-}" ] && BUILD_SET=1
export BUILD_SET
CHANNEL=${FAMILIA_CHANNEL:-bleeding}; STABLE_DAYS=${FAMILIA_STABLE_DAYS:-30}

[ "${INSTALL_NO_START:-0}" = 1 ] && NO_START=1
[ "${INSTALL_NO_PATH:-0}" = 1 ] && NOPATH=1

say() { printf 'familia-unix: %s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }
run() { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }

# Parse arguments
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) shift; [ -n "${1:-}" ] || die "--prefix needs a directory path"; PREFIX=$1 ;;
    --dry-run|-n) DRY=1 ;;
    --yes|-y)
      INSTALL_ACK=yes
      FAMILIA_ACCEPT_LICENSES=yes
      export INSTALL_ACK FAMILIA_ACCEPT_LICENSES
      FAMILIA_ALLOW_ROOT=${FAMILIA_ALLOW_ROOT:-yes}
      ;;
    --accept-unknown) FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes; export FAMILIA_ACCEPT_UNKNOWN_LICENSES ;;
    --allow-root) FAMILIA_ALLOW_ROOT=yes ;;
    --auto-deps) AUTO_DEPS=1; export AUTO_DEPS ;;
    --uninstall) UNINSTALL=1 ;;
    --purge) PURGE=1 ;;
    --name) shift; NAME=${1:-} ;;
    --branch) shift; [ -n "${1:-}" ] || die "--branch needs a branch name"; BRANCH=$1; SELECT_BRANCH=1 ;;
    --build) shift; BUILD=${1:-}; BUILD_SET=1 ;;
    --no-runtime) RUNTIME=0 ;;
    --no-start) NO_START=1 ;;
    --no-pgo) PGO=0 ;;
    --no-hermes) HERMES=0 ;;
    --no-path) NOPATH=1 ;;
    --systemd) SYSTEMD=1 ;;
    --no-wakelock) WAKELOCK=0 ;;
    --sshd) SSHD=1 ;;
    --channel) shift; CHANNEL=${1:-} ;;
    --stable-days) shift; STABLE_DAYS=${1:-} ;;
    --force-host) FORCE_HOST=--force ;;
    -h|--help)
      sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
  shift
done

# Dry-run early exit preview
if [ "$DRY" = 1 ]; then
  say "[dry-run] release channel $CHANNEL (stable window $STABLE_DAYS days)"
  say "[dry-run] install target prefix: $PREFIX${BRANCH:+ on branch $BRANCH}"
  say "[dry-run] would install preliminary stock if missing: sh install/deps.sh --install (git/curl/python3/...)"
  say "[dry-run] would ensure Charm gum in ~/.local/bin: sh scripts/install-gum.sh --dry-run"
  say "[dry-run] would show license review (scripts/licenses.py gate)"
  say "[dry-run] would download/build inference runtime (llama.cpp) if enabled"
  say "[dry-run] would setup Hermes agent and measure host into graph.yaml"
  [ "$NOPATH" = 1 ] || say "[dry-run] would put familia on PATH: sh scripts/install-cli.sh"
  [ "$NO_START" = 1 ] || say "[dry-run] would start: $PREFIX/bin/familia-start"
  exit 0
fi

# Platform detection
PLATFORM="unknown"
if [ -n "${TERMUX_VERSION:-}" ] || [ -d /data/data/com.termux/files/usr ]; then
  PLATFORM="termux"
else
  UNAME_S=$(uname -s 2>/dev/null || echo unknown)
  case "$UNAME_S" in
    Linux) PLATFORM="linux" ;;
    Darwin) PLATFORM="macos" ;;
    FreeBSD) PLATFORM="freebsd" ;;
    *) die "unsupported operating system: $UNAME_S" ;;
  esac
fi

ARCH=$(uname -m 2>/dev/null || echo unknown)
say "detected platform: $PLATFORM ($ARCH)"

# Validate release channel
case "$CHANNEL" in bleeding|stable) ;; *) die "invalid --channel (use bleeding or stable)" ;; esac
case "$STABLE_DAYS" in ''|*[!0-9]*|0*|????*) die "invalid --stable-days (an integer 1..365)" ;; esac
[ "$STABLE_DAYS" -le 365 ] || die "invalid --stable-days (an integer 1..365)"
FAMILIA_CHANNEL=$CHANNEL; FAMILIA_STABLE_DAYS=$STABLE_DAYS; export FAMILIA_CHANNEL FAMILIA_STABLE_DAYS

# Root check
if [ "$(id -u 2>/dev/null || echo 1)" = 0 ] && [ "$PLATFORM" != "termux" ]; then
  say "warning: running as root is not recommended; this installer targets user-space ($PREFIX)"
  case "${FAMILIA_ALLOW_ROOT:-}" in
    [Yy][Ee][Ss]) say "continuing as root (FAMILIA_ALLOW_ROOT=yes)" ;;
    *)
      if [ -t 0 ]; then
        printf 'Type yes to continue as root: ' >&2
        ans=""; read -r ans || ans=""
        case "$ans" in [Yy][Ee][Ss]) say "continuing as root" ;; *) die "not confirmed; aborting" ;; esac
      else
        die "running as root needs an attestation (--allow-root, --yes, or FAMILIA_ALLOW_ROOT=yes)"
      fi ;;
  esac
fi

# Contribution acknowledgement (non-blocking if INSTALL_ACK=yes or --yes)
ack_notice() {
  case "${INSTALL_ACK:-}" in
    yes) return 0 ;;
    no) die "not acknowledged" ;;
  esac
  if [ "${FAMILIA_ACCEPT_LICENSES:-}" = yes ]; then
    return 0
  fi
  say "This product includes software developed by Brian Fundakowski Feldman."
  say "If this is useful, a contribution toward rent, groceries, or keeping the lights on is welcome."
  if [ ! -r /dev/tty ]; then
    die "type yes on a terminal, or set INSTALL_ACK=yes (or pass --yes)"
  fi
  printf 'familia-unix: type yes to continue: ' >&2
  read -r ans < /dev/tty || die "no acknowledgement"
  case "$ans" in
    yes|y) ;;
    *) die "not acknowledged" ;;
  esac
}
ack_notice

# Directory layout paths under $PREFIX
BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/lib"
LIBEXEC_DIR="$PREFIX/libexec/familia"
SHARE_DIR="$PREFIX/share/familia"
SKILLS_DIR="$SHARE_DIR/skills"
MODELS_DIR="$SHARE_DIR/models"
ETC_DIR="$PREFIX/etc/familia"
SRC_DIR="$PREFIX/src"
REPO_DIR="$SRC_DIR/familia"
# If installing directly into a cloned repo target (e.g. bootstrap test), use $PREFIX directly
if [ -d "$PREFIX/.git" ]; then
  REPO_DIR="$PREFIX"
fi
HERMES_DIR="$SRC_DIR/hermes-agent"
KEY_FILE="$ETC_DIR/api.key"
LAUNCHER="$BIN_DIR/familia-start"

# Supervision unit targets
SYSTEMD_UNIT="$HOME/.config/systemd/user/familia-node.service"
MACOS_PLIST="$HOME/Library/LaunchAgents/com.brianreborn.familia-node.plist"
TERMUX_BOOT_DIR="$HOME/.termux/boot"
TERMUX_BOOT_SCRIPT="$TERMUX_BOOT_DIR/familia-node.sh"

# Handle uninstall
if [ "$UNINSTALL" = 1 ]; then
  say "uninstalling from $PREFIX..."
  if [ "$PLATFORM" = "linux" ] && [ -f "$SYSTEMD_UNIT" ]; then
    run systemctl --user disable --now familia-node.service 2>/dev/null || true
    run rm -f "$SYSTEMD_UNIT"
  elif [ "$PLATFORM" = "macos" ] && [ -f "$MACOS_PLIST" ]; then
    run launchctl unload "$MACOS_PLIST" 2>/dev/null || true
    run rm -f "$MACOS_PLIST"
  elif [ "$PLATFORM" = "termux" ] && [ -f "$TERMUX_BOOT_SCRIPT" ]; then
    run rm -f "$TERMUX_BOOT_SCRIPT"
  fi

  if [ -L "$SYMLINK_PREFIX" ]; then
    _target=$(readlink "$SYMLINK_PREFIX" 2>/dev/null || true)
    if [ "$_target" = "$PREFIX" ] || [ "$_target" = "$PREFIX/" ]; then
      run rm -f "$SYMLINK_PREFIX"
    fi
  fi

  _cli_shim="$HOME/.local/bin/familia"
  [ -f "$_cli_shim" ] && run rm -f "$_cli_shim"

  if [ "$PURGE" = 1 ]; then
    run rm -rf -- "$PREFIX"
    say "purged entire prefix $PREFIX"
  else
    run rm -rf -- "$BIN_DIR" "$LIB_DIR" "$LIBEXEC_DIR" "$SRC_DIR"
    say "uninstalled executables and source; kept $MODELS_DIR and $ETC_DIR (use --purge to remove all)"
  fi
  say "uninstall complete"; exit 0
fi

# Setup directory hierarchy
say "install target prefix: $PREFIX"
run mkdir -p "$BIN_DIR" "$LIB_DIR" "$LIBEXEC_DIR" "$SKILLS_DIR" "$MODELS_DIR" "$ETC_DIR" "$SRC_DIR"

if [ "$PREFIX" = "$DEFAULT_PREFIX" ]; then
  _link_dir=$(dirname "$SYMLINK_PREFIX")
  run mkdir -p "$_link_dir"
  ln -sfn "$PREFIX" "$SYMLINK_PREFIX"
fi

# Ensure dependencies via install/deps.sh
SCRIPT_SELF_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT_SRC=$(CDPATH='' cd -- "$SCRIPT_SELF_DIR/../.." 2>/dev/null && pwd || true)
DEPS_SH=""
if [ -f "$REPO_ROOT_SRC/install/deps.sh" ]; then DEPS_SH="$REPO_ROOT_SRC/install/deps.sh";
elif [ -f "$PREFIX/install/deps.sh" ]; then DEPS_SH="$PREFIX/install/deps.sh";
fi

if [ -n "$DEPS_SH" ]; then
  if ! sh "$DEPS_SH" >/dev/null 2>&1; then
    if [ "$AUTO_DEPS" != 1 ]; then
      say "preliminary OS packages missing"
      sh "$DEPS_SH" || true
      if ! python3 -c 'import yaml' >/dev/null 2>&1; then
        python3 -m pip install --user --quiet pyyaml >/dev/null 2>&1 \
          || python3 -m pip install --user --break-system-packages --quiet pyyaml >/dev/null 2>&1 || true
      fi
      if sh "$DEPS_SH" >/dev/null 2>&1; then
        say "preliminary packages satisfied without root"
      else
        die "install the packages with the command above, or re-run with --auto-deps (or AUTO_DEPS=1) to install them (needs root)"
      fi
    else
      say "WARNING: the next step installs OS packages AS ROOT (sudo / package manager)."
      if [ "${INSTALL_ACK:-}" = yes ] || [ "${FAMILIA_ACCEPT_LICENSES:-}" = yes ]; then
        sh "$DEPS_SH" --install --yes || die "deps install failed; see docs/safe-mode-bootstrap.md"
      else
        sh "$DEPS_SH" --install || die "deps install failed or declined"
      fi
    fi
  fi
fi

# Clone or update the familia repository under $REPO_DIR
if [ -d "$REPO_DIR/.git" ]; then
  if [ -n "$BRANCH" ]; then
    git -C "$REPO_DIR" fetch -q origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" || die "fetch origin/$BRANCH failed"
    if git -C "$REPO_DIR" show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git -C "$REPO_DIR" switch -q "$BRANCH" || die "switch to $BRANCH failed"
    else
      git -C "$REPO_DIR" switch -q --track -c "$BRANCH" "origin/$BRANCH" || die "track origin/$BRANCH failed"
    fi
    git -C "$REPO_DIR" branch --set-upstream-to="origin/$BRANCH" "$BRANCH" >/dev/null 2>&1 || true
    git -C "$REPO_DIR" merge --ff-only -q "origin/$BRANCH" || say "warning: fast-forward merge failed; keeping local state"
  else
    git -C "$REPO_DIR" pull --ff-only -q >/dev/null 2>&1 || say "warning: repo not fast-forwardable; left as is"
  fi
elif [ -d "$REPO_ROOT_SRC/.git" ] && [ "$REPO_ROOT_SRC" != "$REPO_DIR" ] && [ -z "${FAMILIA_REPO_URL:-}" ]; then
  if [ -n "$BRANCH" ]; then
    git clone -q --branch "$BRANCH" "$REPO_ROOT_SRC" "$REPO_DIR" 2>/dev/null ||
      git clone -q "$REPO_URL" "$REPO_DIR"
  else
    git clone -q "$REPO_ROOT_SRC" "$REPO_DIR" 2>/dev/null ||
      git clone -q "$REPO_URL" "$REPO_DIR"
  fi
else
  if [ -n "$BRANCH" ]; then
    git clone -q --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
  else
    git clone -q "$REPO_URL" "$REPO_DIR"
  fi
fi

# Ensure Charm gum via scripts/install-gum.sh
GUM_SH=""
if [ -f "$REPO_DIR/scripts/install-gum.sh" ]; then GUM_SH="$REPO_DIR/scripts/install-gum.sh";
elif [ -f "$REPO_ROOT_SRC/scripts/install-gum.sh" ]; then GUM_SH="$REPO_ROOT_SRC/scripts/install-gum.sh";
fi
if [ -n "$GUM_SH" ]; then
  say "ensuring Charm gum in ~/.local/bin..."
  GUM_FLAGS=""
  if [ "${INSTALL_ACK:-}" = yes ] || [ "${FAMILIA_ACCEPT_LICENSES:-}" = yes ]; then
    GUM_FLAGS="--yes"
  fi
  # shellcheck disable=SC2086
  sh "$GUM_SH" $GUM_FLAGS 2>/dev/null || say "warning: gum not installed; fallback: ./familia --legacy-menu"
fi

# License review gate
if [ -f "$REPO_DIR/scripts/licenses.py" ]; then
  python3 "$REPO_DIR/scripts/licenses.py" gate || die "licenses not accepted"
fi
FAMILIA_ACCEPT_LICENSES=yes; FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes; export FAMILIA_ACCEPT_LICENSES FAMILIA_ACCEPT_UNKNOWN_LICENSES

# Sync pinned parts (pins.txt)
if [ -f "$REPO_DIR/scripts/sync_pins.py" ]; then
  python3 "$REPO_DIR/scripts/sync_pins.py" --root "$REPO_DIR" || say "warning: pins sync had non-fatal errors"
fi

# Copy skills to $SKILLS_DIR
if [ -d "$REPO_DIR/skills" ]; then
  cp -R "$REPO_DIR/skills/"* "$SKILLS_DIR/" 2>/dev/null || true
fi

# Python 3.15+ / Profile-Guided Optimization (PGO) offer
if [ "$PLATFORM" != "termux" ] && [ "$PGO" = 1 ] && [ "$RUNTIME" = 1 ] && [ "$NO_START" != 1 ]; then
  PY_NEEDS_PGO=0
  python3 -c 'import sys; sys.exit(0 if sys.version_info < (3, 15) else 1)' 2>/dev/null && PY_NEEDS_PGO=1 || true
  if [ "$PY_NEEDS_PGO" = 1 ]; then
    DO_PGO=0
    if [ "${FAMILIA_ACCEPT_LICENSES:-}" = "yes" ]; then
      DO_PGO=0 # Skip full compilation in fast unattended tests unless requested
    elif [ -t 0 ]; then
      PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
      printf 'Python %s detected (< 3.15). Build optimized Python 3.15+ with PGO & LTO into prefix? [y/N]: ' "$PY_VER" >&2
      ans=""; read -r ans || ans=""
      case "$ans" in [Yy]*) DO_PGO=1 ;; *) DO_PGO=0 ;; esac
    fi

    if [ "$DO_PGO" = 1 ]; then
      say "building Python with PGO optimizations into $PREFIX (this may take several minutes)..."
      NPROC=$(nproc 2>/dev/null || getconf NPROCESSORS_ONLN 2>/dev/null || echo 2)
      PGO_TMP=$(umask 077; mktemp -d "${TMPDIR:-/tmp}/py-pgo.XXXXXX") || die "mktemp failed"
      (
        cd "$PGO_TMP"
        PY_TAR="Python-3.15.0a1.tar.xz"
        PY_SRC_URL="https://www.python.org/ftp/python/3.15.0/$PY_TAR"
        if curl -fsSL -o "$PY_TAR" "$PY_SRC_URL" 2>/dev/null; then
          tar -xf "$PY_TAR"
          cd Python-3.15*
          ./configure --enable-optimizations --with-lto --prefix="$PREFIX" >/dev/null 2>&1
          make -j"$NPROC" >/dev/null 2>&1
          make install >/dev/null 2>&1
          say "Python PGO runtime installed into $PREFIX/bin"
        else
          say "note: Python 3.15 tarball not fetched; using system python"
        fi
      ) || say "warning: Python PGO build skipped; using system python"
      rm -rf -- "$PGO_TMP"
    fi
  fi
fi

# Install Engine (llama.cpp)
if [ "$RUNTIME" = 1 ] && [ "$NO_START" != 1 ]; then
  if [ "$PLATFORM" = "termux" ]; then
    say "installing llama-cpp via Termux pkg..."
    pkg install -y llama-cpp 2>/dev/null || say "warning: pkg install llama-cpp failed (ensure repo is updated)"
  elif [ "$PLATFORM" = "freebsd" ]; then
    say "FreeBSD source build for llama.cpp..."
    LLAMA_SRC="$SRC_DIR/code-bootstraps-llama.cpp"
    if [ ! -d "$LLAMA_SRC" ]; then
      git clone -q https://github.com/brianreborn/llama.cpp.git "$LLAMA_SRC" 2>/dev/null || true
    fi
    if [ -d "$LLAMA_SRC" ] && command -v cmake >/dev/null 2>&1; then
      (
        cd "$LLAMA_SRC"
        cmake -B build -DGGML_OPENMP=OFF -DLLAMA_BUILD_EXAMPLES=OFF >/dev/null 2>&1
        cmake --build build -j"$(getconf NPROCESSORS_ONLN 2>/dev/null || echo 2)" --target llama-server >/dev/null 2>&1
        cp build/bin/llama-server "$BIN_DIR/llama-server" 2>/dev/null || true
      ) || say "warning: FreeBSD llama.cpp source build failed; check cmake/compiler"
    fi
  else
    ASSET_RE=""
    case "$PLATFORM/$ARCH" in
      linux/x86_64) ASSET_RE='bin-ubuntu-x64\.(tar\.gz|zip)$' ;;
      linux/aarch64) ASSET_RE='bin-ubuntu-arm64\.(tar\.gz|zip)$' ;;
      macos/arm64) ASSET_RE='bin-macos-arm64\.(tar\.gz|zip)$' ;;
      macos/x86_64) ASSET_RE='bin-macos-x64\.(tar\.gz|zip)$' ;;
      *) say "warning: no pre-built binary for $PLATFORM/$ARCH; skipping binary download" ;;
    esac

    if [ -n "$ASSET_RE" ]; then
      URL="$API/tags/$BUILD"
      say "querying llama.cpp release asset ($BUILD)..."
      JSON=$(curl -fsSL -H 'Accept: application/vnd.github+json' "$URL" 2>/dev/null || echo "{}")
      SEL=$(printf '%s' "$JSON" | ASSET_RE="$ASSET_RE" python3 -c '
import json, os, re, sys
try:
    j = json.load(sys.stdin)
    hits = [a for a in j.get("assets", []) if re.search(os.environ["ASSET_RE"], a.get("name", ""))]
    if hits:
        a = hits[0]
        d = a.get("digest") or ""
        sha = d.split(":", 1)[1] if d.startswith("sha256:") else ""
        print(j.get("tag_name", "b11539"), a.get("name"), a.get("browser_download_url"), sha)
except Exception:
    pass
' 2>/dev/null || true)
      if [ -n "$SEL" ]; then
        set -- $SEL
        _tag=$1; ANAME=$2; AURL=$3; SHA=${4:-}
        : "$_tag"
        TMP=$(umask 077; mktemp -d "${TMPDIR:-/tmp}/llama-bin.XXXXXX") || die "mktemp failed"
        if curl -fL --retry 3 -o "$TMP/$ANAME" "$AURL" 2>/dev/null; then
          if [ -n "$SHA" ]; then
            if command -v sha256sum >/dev/null 2>&1; then GOT=$(sha256sum "$TMP/$ANAME" | cut -d' ' -f1);
            else GOT=$(shasum -a 256 "$TMP/$ANAME" | cut -d' ' -f1); fi
            [ "$GOT" = "$SHA" ] || die "sha256 mismatch for $ANAME"
          fi
          case "$ANAME" in
            *.zip) unzip -q -o "$TMP/$ANAME" -d "$TMP/ext" ;;
            *) mkdir -p "$TMP/ext"; tar -xzf "$TMP/$ANAME" -C "$TMP/ext" ;;
          esac
          S=$(find "$TMP/ext" -name llama-server -type f | head -n 1)
          if [ -n "$S" ]; then
            cp "$S" "$BIN_DIR/llama-server"
            chmod 755 "$BIN_DIR/llama-server"
            say "llama-server binary installed to $BIN_DIR/llama-server"
          fi
        fi
        rm -rf -- "$TMP"
      fi
    fi
  fi
fi

# Auto-install Hermes Agent (skip if offline/test repo without remote network or --no-start / --no-runtime)
if [ "$HERMES" = 1 ] && [ "$RUNTIME" = 1 ] && [ "$NO_START" != 1 ] && [ -z "${FAMILIA_TEST_OFFLINE:-}" ]; then
  if [ "$PLATFORM" = "termux" ]; then
    say "resolving Hermes Agent (Termux development branch)..."
    if [ ! -d "$HERMES_DIR/.git" ]; then
      git clone -q --depth 1 -b development https://github.com/NousResearch/hermes-agent.git "$HERMES_DIR" 2>/dev/null || true
    fi
  else
    say "resolving Hermes Agent (pinned release)..."
    HERMES_COMMIT="f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab"
    if [ -f "$REPO_DIR/config/hermes-agent.pins.json" ]; then
      _hc=$(python3 -c '
import json
try:
    with open("'"$REPO_DIR"'/config/hermes-agent.pins.json") as f:
        print(json.load(f)["channels"]["bleeding"]["commit"])
except Exception:
    pass
' 2>/dev/null || true)
      [ -n "$_hc" ] && HERMES_COMMIT="$_hc"
    fi
    if [ ! -d "$HERMES_DIR/.git" ]; then
      git clone -q https://github.com/NousResearch/hermes-agent.git "$HERMES_DIR" 2>/dev/null || true
      git -C "$HERMES_DIR" checkout -q "$HERMES_COMMIT" 2>/dev/null || true
    fi
  fi

  if [ -f "$HERMES_DIR/bin/hermes" ]; then
    ln -sfn "$HERMES_DIR/bin/hermes" "$BIN_DIR/hermes"
  elif [ -f "$HERMES_DIR/hermes" ]; then
    ln -sfn "$HERMES_DIR/hermes" "$BIN_DIR/hermes"
  fi
fi

# Generate API key at $KEY_FILE (0600)
if [ ! -e "$KEY_FILE" ]; then
  mkdir -p "$ETC_DIR"
  _key_hex=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  printf '%s' "$_key_hex" > "$KEY_FILE.tmp.$$"
  chmod 600 "$KEY_FILE.tmp.$$"
  mv -f "$KEY_FILE.tmp.$$" "$KEY_FILE"
  say "generated API key at $KEY_FILE (mode 0600)"
fi

# Measure host and write to graph.yaml
[ -n "$NAME" ] || {
  NAME=$(hostname 2>/dev/null | cut -d. -f1 | tr '[:upper:]' '[:lower:]')
  if [ -n "$NAME" ] && [ -t 0 ] && [ "${FAMILIA_ACCEPT_LICENSES:-}" != "yes" ] && [ "$DRY" != 1 ]; then
    printf 'Host name for graph.yaml [%s]: ' "$NAME" >&2
    IFS= read -r ANSWER || ANSWER=""
    [ -z "$ANSWER" ] || NAME=$ANSWER
  fi
}
[ -n "$NAME" ] || NAME="local-node"

GRAPH_FILE="$ETC_DIR/graph.yaml"
if [ ! -f "$GRAPH_FILE" ] && [ -f "$REPO_DIR/graph.yaml" ]; then
  mkdir -p "$ETC_DIR"
  cp "$REPO_DIR/graph.yaml" "$GRAPH_FILE"
fi
if [ -f "$REPO_DIR/scripts/host_measure.py" ]; then
  KIND="desktop"
  [ "$PLATFORM" = "termux" ] && KIND="phone"
  [ -d /sys/class/power_supply/BAT0 ] && KIND="laptop"
  if ! python3 "$REPO_DIR/scripts/host_measure.py" --name "$NAME" --kind "$KIND" --graph "$GRAPH_FILE" $FORCE_HOST; then
    say "warning: host measurement failed; no measured graph record was written"
  fi
fi

# Generate Launcher: $BIN_DIR/familia-start
cat > "$LAUNCHER" <<EOS
#!/bin/sh
# familia-start: unified node launcher ($PREFIX)
set -eu
: "\${FAMILIA_MODEL:?set FAMILIA_MODEL to a GGUF file path or a model name in $MODELS_DIR}"
M="\$FAMILIA_MODEL"
[ -f "\$M" ] || M="$MODELS_DIR/\$FAMILIA_MODEL"

B="$BIN_DIR/llama-server"
if [ ! -x "\$B" ]; then
  B=\$(command -v llama-server 2>/dev/null || true)
fi
[ -n "\$B" ] && [ -x "\$B" ] || { echo "familia-start: llama-server executable not found" >&2; exit 2; }

echo "familia-start: logs to stdout/stderr" >&2

# Security checks
familia_extra_check() {
  set -f
  for _t in \${FAMILIA_EXTRA:-} "\$@"; do
    case "\$_t" in
      --host*|--port*|--api-key*|--ssl*|--path*)
        echo "familia-start: token \$_t would override bind/port/auth/TLS/path; refusing" >&2
        exit 2
        ;;
    esac
  done
}

# Canonical store is instances/<port>/api-keys (#419). $KEY_FILE is a migration source.
familia_key_args() {
  _port="\${FAMILIA_PORT:-9941}"
  case "\$_port" in *[!0-9]*) echo "familia-start: FAMILIA_PORT must be a number; refusing" >&2; exit 2 ;; esac
  if [ "\$_port" -lt 1 ] || [ "\$_port" -gt 65535 ]; then echo "familia-start: FAMILIA_PORT must be 1-65535; refusing" >&2; exit 2; fi
  _base="\${XDG_CONFIG_HOME:-\$HOME/.config}"
  _inst="\$_base/familia/instances/\$_port/api-keys"
  _legacy="$KEY_FILE"
  if [ -n "\${FAMILIA_API_KEY_FILE:-}" ]; then
    KF="\$FAMILIA_API_KEY_FILE"
  elif [ -e "\$_inst" ] || [ -L "\$_inst" ]; then
    KF="\$_inst"
  elif [ -e "\$_legacy" ] || [ -L "\$_legacy" ]; then
    [ -L "\$_legacy" ] && { echo "familia-start: \$_legacy is a symlink; refusing" >&2; exit 2; }
    [ -f "\$_legacy" ] || { echo "familia-start: \$_legacy is not a regular file" >&2; exit 2; }
    _tok=\$(tr -d '[:space:]' < "\$_legacy")
    [ -n "\$_tok" ] || { echo "familia-start: \$_legacy is empty; refusing" >&2; exit 2; }
    _dir=\$(dirname "\$_inst")
    ( umask 077; mkdir -p "\$_dir" ) || { echo "familia-start: cannot create \$_dir; refusing" >&2; exit 2; }
    _tmp="\$_dir/.api-keys.\$\$"
    rm -f "\$_tmp"
    ( umask 077; set -C; printf '%s\n' "# llama-server API key(s), one per line" "\$_tok" > "\$_tmp" ) || {
      echo "familia-start: cannot write \$_tmp; refusing" >&2; exit 2; }
    chmod 600 "\$_tmp" || { rm -f "\$_tmp"; echo "familia-start: cannot chmod \$_tmp; refusing" >&2; exit 2; }
    if [ -L "\$_inst" ]; then rm -f "\$_tmp"; echo "familia-start: \$_inst is a symlink; refusing" >&2; exit 2; fi
    if [ ! -e "\$_inst" ]; then
      if ln "\$_tmp" "\$_inst" 2>/dev/null; then rm -f "\$_tmp"
      elif [ ! -e "\$_inst" ] && mv "\$_tmp" "\$_inst" 2>/dev/null; then chmod 600 "\$_inst"
      else rm -f "\$_tmp"; echo "familia-start: cannot publish \$_inst; refusing" >&2; exit 2
      fi
      echo "familia-start: migrated API key from \$_legacy into \$_inst (#419). \$_legacy is a migration source only and is not used for lookup." >&2
    else
      rm -f "\$_tmp"
    fi
    KF="\$_inst"
  else
    echo "familia-start: API key file \$_legacy missing (0600 required)" >&2; exit 2
  fi
  [ -e "\$KF" ] || { echo "familia-start: API key file \$KF missing (0600 required)" >&2; exit 2; }
  [ -L "\$KF" ] && { echo "familia-start: \$KF is a symlink; refusing" >&2; exit 2; }
  _r=\$(realpath -e -- "\$KF" 2>/dev/null) || _r="\$KF"
  KF="\$_r"
  [ -f "\$KF" ] || { echo "familia-start: \$KF is not a regular file" >&2; exit 2; }
  FAMILIA_KF="\$KF"
}

familia_env_scrub() {
  unset LLAMA_API_KEY LLAMA_ARG_API_KEY_FILE
  for _v in \$(env | sed -n 's/^\(LLAMA_ARG_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "\$_v"; done
}

familia_tools_check() {
  _h="\$1"; shift
  case "\$_h" in 127.0.0.1|localhost|::1) return 0 ;; esac
  for _t in \${FAMILIA_EXTRA:-} "\$@"; do
    case "\$_t" in --tools*) echo "familia-start: --tools allowed only on loopback bind; refusing" >&2; exit 2 ;; esac
  done
}

familia_extra_check "\$@"
familia_key_args
familia_env_scrub

H="\${FAMILIA_BIND:-127.0.0.1}"; [ "\$H" = '[::1]' ] && H=::1
familia_tools_check "\$H" "\$@"

exec "\$B" -m "\$M" --host "\$H" --port "\${FAMILIA_PORT:-9941}" -c "\${FAMILIA_CTX:-4096}" --api-key-file "\$FAMILIA_KF" "\$@" \${FAMILIA_EXTRA:-}
EOS
chmod 755 "$LAUNCHER"
say "wrote launcher $LAUNCHER"

# Put familia on PATH via scripts/install-cli.sh
CLI_SH=""
if [ -f "$REPO_DIR/scripts/install-cli.sh" ]; then CLI_SH="$REPO_DIR/scripts/install-cli.sh";
elif [ -f "$REPO_ROOT_SRC/scripts/install-cli.sh" ]; then CLI_SH="$REPO_ROOT_SRC/scripts/install-cli.sh";
fi
if [ "$NOPATH" != 1 ] && [ -n "$CLI_SH" ]; then
  sh "$CLI_SH" >&2 || say "warning: could not put familia on PATH: scripts/install-cli.sh"
fi

# Background service supervision setup
case "$PLATFORM" in
  linux)
    if [ "$SYSTEMD" = 1 ]; then
      mkdir -p "$(dirname "$SYSTEMD_UNIT")"
      cat > "$SYSTEMD_UNIT" <<EOS
[Unit]
Description=familia node ($PREFIX)
After=network.target

[Service]
Type=simple
EnvironmentFile=-%h/.config/familia/node.env
ExecStart=$LAUNCHER
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=default.target
EOS
      say "wrote systemd user unit: $SYSTEMD_UNIT"
      say "to enable: systemctl --user enable --now familia-node"
    fi
    ;;
  macos)
    mkdir -p "$(dirname "$MACOS_PLIST")"
    cat > "$MACOS_PLIST" <<EOS
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.brianreborn.familia-node</string>
  <key>ProgramArguments</key>
  <array>
    <string>$LAUNCHER</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardErrorPath</key>
  <string>$PREFIX/familia-node.log</string>
  <key>StandardOutPath</key>
  <string>$PREFIX/familia-node.log</string>
</dict>
</plist>
EOS
    say "wrote macOS LaunchAgent: $MACOS_PLIST"
    ;;
  termux)
    mkdir -p "$TERMUX_BOOT_DIR"
    cat > "$TERMUX_BOOT_SCRIPT" <<EOS
#!/data/data/com.termux/files/usr/bin/sh
${WAKELOCK:+termux-wake-lock}
exec "$LAUNCHER" >/dev/null 2>&1 &
EOS
    chmod +x "$TERMUX_BOOT_SCRIPT"
    if [ "$WAKELOCK" = 1 ] && command -v termux-wake-lock >/dev/null 2>&1; then
      termux-wake-lock 2>/dev/null || true
    fi
    if [ "$SSHD" = 1 ]; then
      pkg install -y openssh 2>/dev/null || true
      sshd 2>/dev/null || true
    fi
    say "wrote Termux boot script: $TERMUX_BOOT_SCRIPT"
    ;;
  freebsd)
    say "FreeBSD supervision: add to crontab: @reboot sleep 30; $LAUNCHER"
    ;;
esac

say "installation completed successfully."
say "prefix root: $PREFIX"
say "active symlink: $SYMLINK_PREFIX"
if [ "$NO_START" = 1 ]; then
  say "stopped after setup (--no-start). Start with: FAMILIA_MODEL=model.gguf $LAUNCHER"
elif [ -f "$PREFIX/start.sh" ]; then
  say "starting FAMILIA..."
  exec sh "$PREFIX/start.sh"
fi
