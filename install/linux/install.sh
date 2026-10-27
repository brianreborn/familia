#!/bin/sh
# familia one-click installer: desktop Linux (Ubuntu/Debian and similar) and macOS.
# Usage: sh install/linux/install.sh [flags]   (flags below)
#   curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install/linux/install.sh | sh
# No sudo. Everything goes under ~/.local (override with FAMILIA_PREFIX).
# Flags: --dry-run  print every action, change nothing
#        --uninstall remove what this script installed (models dir kept unless --purge)
#        --name NAME host name for graph.yaml (default: short hostname, lowercased)
#                     interactive installs prompt with this hostname as the default
#        --build bNNNN llama.cpp release tag (default b11539, familia's verified build;
#                     'latest' = newest bNNNN release that has this platform's asset)
#        --no-runtime  skip the llama.cpp download     --systemd  install a systemd --user unit
#        --branch BRANCH  select the familia branch (default: checkout branch, else main)
#        --force-host  replace an existing hosts.NAME block
#        --yes         accept the license review without a prompt (summary still printed)
#        --accept-unknown  also accept components whose license could not be found
#        --no-path     do not put `familia` on PATH (default: 2-line shim ~/.local/bin/familia, scripts/install-cli.sh)
# Safety: llama.cpp assets are verified against the sha256 digest published by
# the GitHub release API at install time. No hash is hardcoded. Idempotent.
# Example: sh install/linux/install.sh --dry-run
set -eu

PREFIX=${FAMILIA_PREFIX:-$HOME/.local/share/familia}
BIN_DIR=${FAMILIA_BIN_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}
REPO_URL=${FAMILIA_REPO_URL:-https://github.com/brianreborn/familia.git}
SOURCE_BRANCH=""
if [ -f "$0" ]; then
  SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." 2>/dev/null && pwd || true)
  if [ -n "$SOURCE_ROOT" ] && git -C "$SOURCE_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    SOURCE_BRANCH=$(git -C "$SOURCE_ROOT" branch --show-current 2>/dev/null || true)
  fi
fi
BRANCH=${FAMILIA_BRANCH:-${SOURCE_BRANCH:-main}}
SELECT_BRANCH=0
{ [ -n "${FAMILIA_BRANCH:-}" ] || [ -n "$SOURCE_BRANCH" ]; } && SELECT_BRANCH=1
API=${FAMILIA_LLAMA_API:-https://api.github.com/repos/ggml-org/llama.cpp/releases}
DRY=0; UNINSTALL=0; PURGE=0; NAME=""; BUILD=${FAMILIA_LLAMA_BUILD:-b11539}; RUNTIME=1; SYSTEMD=0; FORCE_HOST=""; NOPATH=0

say() { echo "familia-install: $*" >&2; }
die() { say "error: $*"; exit 1; }
run() { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --branch) shift; [ -n "${1:-}" ] || die "--branch needs a branch name"; BRANCH=$1; SELECT_BRANCH=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --purge) PURGE=1 ;;
    --name) shift; NAME=${1:-} ;;
    --build) shift; BUILD=${1:-} ;;
    --no-runtime) RUNTIME=0 ;;
    --systemd) SYSTEMD=1 ;;
    --no-path) NOPATH=1 ;;
    --force-host) FORCE_HOST=--force ;;
    --yes|-y) FAMILIA_ACCEPT_LICENSES=yes; export FAMILIA_ACCEPT_LICENSES ;;
    --accept-unknown) FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes; export FAMILIA_ACCEPT_UNKNOWN_LICENSES ;;
    -h|--help) sed -n '2,18p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//' || true; exit 0 ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
  shift
done

git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || die "invalid branch name: $BRANCH"

[ "$(id -u)" = 0 ] && die "do not run as root; this installer is user-space only"
UNIT="$HOME/.config/systemd/user/familia-node.service"

if [ "$UNINSTALL" = 1 ]; then
  if [ -f "$UNIT" ]; then
    run systemctl --user disable --now familia-node.service 2>/dev/null || true
    run rm -f "$UNIT"
  fi
  run rm -f "$BIN_DIR/familia-start"
  if [ -f "$PREFIX/repo/scripts/install-cli.sh" ]; then  # the PATH shim etc., exactly what it recorded
    if [ "$DRY" = 1 ]; then XDG_BIN_HOME=$BIN_DIR sh "$PREFIX/repo/scripts/install-cli.sh" uninstall --dry-run
    else XDG_BIN_HOME=$BIN_DIR sh "$PREFIX/repo/scripts/install-cli.sh" uninstall --yes; fi
  fi
  if [ "$PURGE" = 1 ]; then run rm -rf "$PREFIX"
  else
    run rm -rf "$PREFIX/repo" "$PREFIX/runtime"
    say "kept $PREFIX/models (use --purge to remove it)"
  fi
  say "uninstalled"; exit 0
fi

# Prefer the unified dispatcher when this checkout has it (safe-mode bootstrap).
DEPS_SH=""
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -f "$SCRIPT_DIR/../deps.sh" ] && DEPS_SH="$SCRIPT_DIR/../deps.sh"
[ -z "$DEPS_SH" ] && [ -f "$SCRIPT_DIR/deps.sh" ] && DEPS_SH="$SCRIPT_DIR/deps.sh"
need_tools=0
for c in git curl python3; do command -v "$c" >/dev/null 2>&1 || need_tools=1; done
command -v tar >/dev/null 2>&1 || [ "$RUNTIME" = 0 ] || need_tools=1
if [ "$need_tools" = 1 ]; then
  if [ -n "$DEPS_SH" ]; then
    say "missing tools; running sh install/deps.sh --install (see docs/safe-mode-bootstrap.md)"
    if [ "$DRY" = 1 ]; then
      say "[dry-run] would run: sh $DEPS_SH --install${FAMILIA_ACCEPT_LICENSES:+ --yes}"
    else
      if [ "${FAMILIA_ACCEPT_LICENSES:-}" = yes ]; then
        sh "$DEPS_SH" --install --yes || die "deps install failed; fix packages then re-run"
      else
        sh "$DEPS_SH" --install || die "deps install failed or declined; see: sh install/deps.sh --help"
      fi
    fi
  else
    for c in git curl python3; do command -v "$c" >/dev/null 2>&1 || die "$c is required (see: sh install/linux/deps.sh --install)"; done
  fi
fi
for c in git curl python3; do command -v "$c" >/dev/null 2>&1 || die "$c is required (see: sh install/deps.sh --install)"; done
command -v tar >/dev/null 2>&1 || [ "$RUNTIME" = 0 ] || die "tar is required (or pass --no-runtime / sh install/deps.sh --install)"
python3 -c 'import yaml' 2>/dev/null || say "warning: python3-yaml missing; graph validation will be skipped (sh install/deps.sh --install)"

OS=$(uname -s); ARCH=$(uname -m)
case "$OS/$ARCH" in
  Linux/x86_64) ASSET_RE='bin-ubuntu-x64\.(tar\.gz|zip)$' ;;
  Linux/aarch64) ASSET_RE='bin-ubuntu-arm64\.(tar\.gz|zip)$' ;;
  Darwin/arm64) ASSET_RE='bin-macos-arm64\.(tar\.gz|zip)$' ;;
  Darwin/x86_64) ASSET_RE='bin-macos-x64\.(tar\.gz|zip)$' ;;
  FreeBSD/amd64) die "FreeBSD is source-build-only; install no packages. Run ./familia sync --branch $BRANCH, then build from code-bootstraps-llama.cpp with BUILD_DIR=build-freebsd GPU=off scripts/build-linux.sh" ;;
  *) die "unsupported platform $OS/$ARCH (Termux: use install/termux/install.sh)" ;;
esac
[ -n "$NAME" ] || {
  NAME=$(hostname 2>/dev/null | cut -d. -f1 | tr '[:upper:]' '[:lower:]')
  if [ -n "$NAME" ] && [ -t 0 ]; then
    printf 'Host name for graph.yaml [%s]: ' "$NAME" >&2
    IFS= read -r ANSWER || ANSWER=""
    [ -z "$ANSWER" ] || NAME=$ANSWER
  fi
}
[ -n "$NAME" ] || die "could not determine host name; pass --name"

say "prefix $PREFIX, host $NAME, platform $OS/$ARCH"
run mkdir -p "$PREFIX/models" "$PREFIX/runtime" "$BIN_DIR"

# 1. repo (idempotent: clone once, then fast-forward only)
if [ -d "$PREFIX/repo/.git" ]; then
  if [ "$SELECT_BRANCH" = 1 ]; then
    if [ "$DRY" = 1 ]; then
      say "[dry-run] would switch $PREFIX/repo to track origin/$BRANCH and fast-forward only"
    else
      git -C "$PREFIX/repo" fetch -q origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" ||
        die "could not fetch origin/$BRANCH"
      if git -C "$PREFIX/repo" show-ref --verify --quiet "refs/heads/$BRANCH"; then
        run git -C "$PREFIX/repo" switch "$BRANCH"
      else
        run git -C "$PREFIX/repo" switch --track -c "$BRANCH" "origin/$BRANCH"
      fi
      run git -C "$PREFIX/repo" branch --set-upstream-to="origin/$BRANCH" "$BRANCH"
      run git -C "$PREFIX/repo" merge --ff-only "origin/$BRANCH" ||
        die "repo branch $BRANCH could not be fast-forwarded; local changes were preserved"
    fi
  else
    run git -C "$PREFIX/repo" pull --ff-only -q || say "warning: repo not fast-forwardable; left as is"
  fi
else
  run git clone -q --branch "$BRANCH" "$REPO_URL" "$PREFIX/repo"
fi

# Licenses before anything else is downloaded (docs/licenses.md).
if [ "$DRY" = 1 ]; then
  say "[dry-run] would show the license review: python3 $PREFIX/repo/scripts/licenses.py gate"
elif [ "$UNINSTALL" != 1 ]; then
  python3 "$PREFIX/repo/scripts/licenses.py" gate || die "licenses not accepted; nothing else was downloaded. Review: python3 $PREFIX/repo/scripts/licenses.py review (or re-run with --yes, plus --accept-unknown for unknown licenses)"
fi
# Every pinned part to its pin, together (scripts/sync_pins.py); again after each later git pull.
if [ "$DRY" = 1 ]; then
  [ -f "$PREFIX/repo/scripts/sync_pins.py" ] && python3 "$PREFIX/repo/scripts/sync_pins.py" --dry-run --root "$PREFIX/repo" || say "[dry-run] would sync the pinned parts (scripts/sync_pins.py)"
elif [ "$UNINSTALL" != 1 ] && [ -f "$PREFIX/repo/scripts/sync_pins.py" ]; then
  python3 "$PREFIX/repo/scripts/sync_pins.py" --root "$PREFIX/repo" || die "the pinned parts could not be synced (see above)"
  python3 "$PREFIX/repo/scripts/sync_pins.py" --root "$PREFIX/repo" --install-hooks || true
fi

# 2. llama.cpp CPU runtime, sha256 verified against the release API digest
if [ "$RUNTIME" = 1 ]; then
  if [ "$BUILD" = latest ]; then URL="$API?per_page=30"; else URL="$API/tags/$BUILD"; fi
  say "querying $URL"
  JSON=$(curl -fsSL -H 'Accept: application/vnd.github+json' "$URL") || die "release API query failed"
  SEL=$(printf '%s' "$JSON" | ASSET_RE="$ASSET_RE" python3 -c '
import json, os, re, sys
j = json.load(sys.stdin)
for r in (j if isinstance(j, list) else [j]):
    if not re.fullmatch(r"b[0-9]+", r.get("tag_name", "")):
        continue
    hit = [a for a in r.get("assets", []) if re.search(os.environ["ASSET_RE"], a["name"])]
    if hit:
        a = hit[0]; d = a.get("digest") or ""
        print(r["tag_name"], a["name"], a["browser_download_url"], d.split(":", 1)[1] if d.startswith("sha256:") else "")
        break
')
  [ -n "$SEL" ] || die "no asset matching $ASSET_RE in release"
  # shellcheck disable=SC2086 # intentional split of four space-free fields
  set -- $SEL
  TAG=$1; ANAME=$2; AURL=$3; SHA=${4:-}
  [ -n "$SHA" ] || die "release API published no sha256 digest for $ANAME; refusing unverified download"
  DEST="$PREFIX/runtime/$TAG"
  if [ -x "$DEST/llama-server" ] || [ -x "$DEST/build/bin/llama-server" ]; then
    say "runtime $TAG already installed"
  elif [ "$DRY" = 1 ]; then
    say "[dry-run] download $AURL, verify sha256 $SHA, extract to $DEST"
  else
    TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
    curl -fL --retry 3 -o "$TMP/$ANAME" "$AURL"
    if command -v sha256sum >/dev/null 2>&1; then GOT=$(sha256sum "$TMP/$ANAME" | cut -d' ' -f1)
    else GOT=$(shasum -a 256 "$TMP/$ANAME" | cut -d' ' -f1); fi
    [ "$GOT" = "$SHA" ] || die "sha256 mismatch for $ANAME: got $GOT want $SHA"
    say "sha256 ok ($SHA)"
    mkdir -p "$DEST"
    case "$ANAME" in
      *.zip) command -v unzip >/dev/null 2>&1 || die "unzip required for $ANAME"; unzip -q -o "$TMP/$ANAME" -d "$DEST" ;;
      *) tar -xzf "$TMP/$ANAME" -C "$DEST" ;;
    esac
    # flatten a single top-level directory so llama-server sits at $DEST or $DEST/build/bin
    S=$(find "$DEST" -name llama-server -type f | head -n 1)
    [ -n "$S" ] || die "llama-server not found in $ANAME"
    D=$(dirname "$S"); [ "$D" = "$DEST" ] || ln -sfn "$S" "$DEST/llama-server"
  fi
  run ln -sfn "$TAG" "$PREFIX/runtime/current"
fi

# 3. measured host entry (never guessed) + graph validation
REPO="$PREFIX/repo"
if [ "$DRY" = 1 ] && [ ! -d "$REPO" ]; then
  say "[dry-run] measure host into $REPO/graph.yaml"
else
  MFLAGS=""; [ "$DRY" = 1 ] && MFLAGS=--dry-run
  KIND=laptop; [ -d /sys/class/power_supply/BAT0 ] || KIND=desktop
  python3 "$REPO/scripts/host_measure.py" --name "$NAME" --kind "$KIND" --graph "$REPO/graph.yaml" $MFLAGS $FORCE_HOST
  # numpy (LittleBit runtime): the spec depends only on the x86-64 level (scripts/cpu_level.py).
  # pre-v2 x86 tries our cpu-baseline=none wheel first when one matches this Python, then numpy<2.4.
  NPCANDS=$(python3 "$REPO/scripts/cpu_level.py" --numpy-candidates 2>/dev/null || echo numpy)
  if ! python3 -c 'import numpy' 2>/dev/null; then
    NPOK=0; for NPSPEC in $NPCANDS; do python3 -m pip install --user --quiet "$NPSPEC" 2>/dev/null && python3 -c 'import numpy' 2>/dev/null && { NPOK=1; break; }; done
    [ "$NPOK" = 1 ] || say "note: numpy not installed (optional; pip install --user '$NPSPEC')"
  fi
  if python3 -c 'import yaml' 2>/dev/null; then
    python3 "$REPO/scripts/validate_graph.py" --no-files --graph "$REPO/graph.yaml" || say "warning: graph validation reported problems (see above)"
  fi
fi

# 4. launcher + optional systemd --user unit (not enabled until a model is set)
LAUNCH="$BIN_DIR/familia-start"
if [ "$DRY" = 1 ]; then say "[dry-run] write $LAUNCH"
else
  cat > "$LAUNCH" <<EOS
#!/bin/sh
# generated by familia install/linux/install.sh
: "\${FAMILIA_MODEL:?set FAMILIA_MODEL to a GGUF path or a name in $PREFIX/models}"
M="\$FAMILIA_MODEL"; [ -f "\$M" ] || M="$PREFIX/models/\$FAMILIA_MODEL"
B="$PREFIX/runtime/current/llama-server"; [ -x "\$B" ] || B="$PREFIX/runtime/current/build/bin/llama-server"
exec "\$B" -m "\$M" --host "\${FAMILIA_BIND:-127.0.0.1}" --port "\${FAMILIA_PORT:-9941}" -c "\${FAMILIA_CTX:-4096}" \${FAMILIA_EXTRA:-}
EOS
  chmod +x "$LAUNCH"
fi
if [ "$SYSTEMD" = 1 ]; then
  if [ "$DRY" = 1 ]; then say "[dry-run] write $UNIT (not enabled)"
  else
    mkdir -p "$(dirname "$UNIT")"
    cat > "$UNIT" <<EOS
[Unit]
Description=familia llama-server node (user)
[Service]
EnvironmentFile=-%h/.config/familia/node.env
ExecStart=$LAUNCH
Restart=on-failure
MemoryHigh=80%
[Install]
WantedBy=default.target
EOS
    say "wrote $UNIT; put FAMILIA_MODEL=... in ~/.config/familia/node.env, then: systemctl --user enable --now familia-node"
  fi
fi
# 5. `familia` on PATH: a 2-line shim in $BIN_DIR that runs $PREFIX/repo/familia (docs/install.md)
if [ "$NOPATH" = 1 ]; then say "--no-path: familia not put on PATH (later: sh $PREFIX/repo/scripts/install-cli.sh)"
elif [ -f "$PREFIX/repo/scripts/install-cli.sh" ]; then
  CF=""; [ "$DRY" = 1 ] && CF=--dry-run
  XDG_BIN_HOME=$BIN_DIR sh "$PREFIX/repo/scripts/install-cli.sh" $CF | sed 's/^/  /' >&2 || say "warning: could not put familia on PATH"
else say "[dry-run] put familia on PATH: sh $PREFIX/repo/scripts/install-cli.sh (shim $BIN_DIR/familia)"; fi
say "done. Models go in $PREFIX/models; start with: FAMILIA_MODEL=x.gguf familia-start"
say "what now: run $PREFIX/repo/familia for the menu (Skills, Models, Agents). Quick start: $PREFIX/repo/QUICKSTART.md"
