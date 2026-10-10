#!/bin/sh
# familia one-click installer: desktop Linux (Ubuntu/Debian and similar) and macOS.
#   curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install/linux/install.sh | sh
# No sudo. Everything goes under ~/.local (override with FAMILIA_PREFIX).
# Flags: --dry-run  print every action, change nothing
#        --uninstall remove what this script installed (models dir kept unless --purge)
#        --name NAME host name for graph.yaml (default: short hostname, lowercased)
#        --build bNNNN llama.cpp release tag (default b11539, familia's verified build;
#                     'latest' = newest bNNNN release that has this platform's asset)
#        --no-runtime  skip the llama.cpp download     --systemd  install a systemd --user unit
#        --force-host  replace an existing hosts.NAME block
# Safety: llama.cpp assets are verified against the sha256 digest published by
# the GitHub release API at install time. No hash is hardcoded. Idempotent.
set -eu

PREFIX=${FAMILIA_PREFIX:-$HOME/.local/share/familia}
BIN_DIR=${FAMILIA_BIN_DIR:-$HOME/.local/bin}
REPO_URL=${FAMILIA_REPO_URL:-https://github.com/brianreborn/familia.git}
BRANCH=${FAMILIA_BRANCH:-main}
API=${FAMILIA_LLAMA_API:-https://api.github.com/repos/ggml-org/llama.cpp/releases}
DRY=0; UNINSTALL=0; PURGE=0; NAME=""; BUILD=${FAMILIA_LLAMA_BUILD:-b11539}; RUNTIME=1; SYSTEMD=0; FORCE_HOST=""

say() { echo "familia-install: $*" >&2; }
die() { say "error: $*"; exit 1; }
run() { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --purge) PURGE=1 ;;
    --name) shift; NAME=${1:-} ;;
    --build) shift; BUILD=${1:-} ;;
    --no-runtime) RUNTIME=0 ;;
    --systemd) SYSTEMD=1 ;;
    --force-host) FORCE_HOST=--force ;;
    -h|--help) sed -n '2,13p' "$0" 2>/dev/null || true; exit 0 ;;
    *) die "unknown flag: $1" ;;
  esac
  shift
done

[ "$(id -u)" = 0 ] && die "do not run as root; this installer is user-space only"
UNIT="$HOME/.config/systemd/user/familia-node.service"

if [ "$UNINSTALL" = 1 ]; then
  if [ -f "$UNIT" ]; then
    run systemctl --user disable --now familia-node.service 2>/dev/null || true
    run rm -f "$UNIT"
  fi
  run rm -f "$BIN_DIR/familia-start"
  if [ "$PURGE" = 1 ]; then run rm -rf "$PREFIX"
  else
    run rm -rf "$PREFIX/repo" "$PREFIX/runtime"
    say "kept $PREFIX/models (use --purge to remove it)"
  fi
  say "uninstalled"; exit 0
fi

for c in git curl python3; do command -v "$c" >/dev/null 2>&1 || die "$c is required (apt install $c)"; done
command -v tar >/dev/null 2>&1 || [ "$RUNTIME" = 0 ] || die "tar is required (or pass --no-runtime)"
python3 -c 'import yaml' 2>/dev/null || say "warning: python3-yaml missing; graph validation will be skipped"

OS=$(uname -s); ARCH=$(uname -m)
case "$OS/$ARCH" in
  Linux/x86_64) ASSET_RE='bin-ubuntu-x64\.(tar\.gz|zip)$' ;;
  Linux/aarch64) ASSET_RE='bin-ubuntu-arm64\.(tar\.gz|zip)$' ;;
  Darwin/arm64) ASSET_RE='bin-macos-arm64\.(tar\.gz|zip)$' ;;
  Darwin/x86_64) ASSET_RE='bin-macos-x64\.(tar\.gz|zip)$' ;;
  *) die "unsupported platform $OS/$ARCH (Termux: use install/termux/install.sh)" ;;
esac
[ -n "$NAME" ] || NAME=$(hostname 2>/dev/null | cut -d. -f1 | tr '[:upper:]' '[:lower:]')
[ -n "$NAME" ] || die "could not determine host name; pass --name"

say "prefix $PREFIX, host $NAME, platform $OS/$ARCH"
run mkdir -p "$PREFIX/models" "$PREFIX/runtime" "$BIN_DIR"

# 1. repo (idempotent: clone once, then fast-forward only)
if [ -d "$PREFIX/repo/.git" ]; then
  run git -C "$PREFIX/repo" pull --ff-only -q || say "warning: repo not fast-forwardable; left as is"
else
  run git clone -q --branch "$BRANCH" "$REPO_URL" "$PREFIX/repo"
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
  if python3 -c 'import yaml' 2>/dev/null; then
    python3 "$REPO/scripts/validate_graph.py" --no-files "$REPO/graph.yaml" || say "warning: graph validation reported problems (see above)"
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
say "done. Models go in $PREFIX/models; start with: FAMILIA_MODEL=x.gguf familia-start"
