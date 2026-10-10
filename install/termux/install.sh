#!/data/data/com.termux/files/usr/bin/sh
# familia one-click installer: Android via Termux (F-Droid or GitHub build, not Play Store).
#   curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install/termux/install.sh | sh
# Runtime comes from Termux's own `llama-cpp` package (pkg verifies package
# signatures/hashes), so no unverified binary is downloaded here.
# Flags: --dry-run  --uninstall [--purge]  --name NAME  --sshd (install+start openssh)
#        --no-runtime  --force-host  --no-wakelock
#   --name defaults to <model>-<last IPv4 octet> (or <model>-<boot_id prefix>), unique per phone.
set -eu

PREFIX_DIR=${FAMILIA_PREFIX:-$HOME/familia}
REPO_URL=${FAMILIA_REPO_URL:-https://github.com/brianreborn/familia.git}
BRANCH=${FAMILIA_BRANCH:-main}
# Phones: Android + apps leave only ~2-2.6 GiB free on a 7.4 GiB A57 (docs/ram-safety.md); policy, not measured.
RESERVE_MIB=${FAMILIA_RESERVE_MIB:-5120}
RAW_URL=${FAMILIA_RAW_URL:-https://raw.githubusercontent.com/brianreborn/familia}
DRY=0; UNINSTALL=0; PURGE=0; NAME=""; SSHD=0; RUNTIME=1; FORCE_HOST=""; WAKE=1

say() { echo "familia-termux: $*" >&2; }
die() { say "error: $*"; exit 1; }
run() { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --purge) PURGE=1 ;;
    --name) shift; NAME=${1:-} ;;
    --sshd) SSHD=1 ;;
    --no-runtime) RUNTIME=0 ;;
    --force-host) FORCE_HOST=--force ;;
    --no-wakelock) WAKE=0 ;;
    -h|--help) sed -n '2,8p' "$0" 2>/dev/null || true; exit 0 ;;
    *) die "unknown flag: $1" ;;
  esac
  shift
done

if [ -z "${TERMUX_VERSION:-}" ] && [ ! -d /data/data/com.termux ]; then
  [ "$DRY" = 1 ] || die "not running inside Termux (use install/linux/install.sh on desktop Linux)"
  say "not in Termux; continuing because --dry-run"
fi
BOOT="$HOME/.termux/boot/familia-node.sh"

if [ "$UNINSTALL" = 1 ]; then
  run rm -f "$BOOT" "$PREFIX/bin/familia-start" 2>/dev/null || true
  if [ "$PURGE" = 1 ]; then run rm -rf "$PREFIX_DIR"
  else run rm -rf "$PREFIX_DIR/repo"; say "kept $PREFIX_DIR/models (use --purge)"; fi
  say "left Termux packages (git python llama-cpp openssh) installed; remove with pkg uninstall if wanted"
  say "uninstalled"; exit 0
fi

PKGS="git python"
[ "$RUNTIME" = 1 ] && PKGS="$PKGS llama-cpp"
[ "$SSHD" = 1 ] && PKGS="$PKGS openssh"
# shellcheck disable=SC2086 # word list
run pkg install -y $PKGS
run pip install --quiet pyyaml || say "warning: pyyaml not installed; graph validation skipped"

if [ "$WAKE" = 1 ]; then
  if command -v termux-wake-lock >/dev/null 2>&1; then run termux-wake-lock
  else say "termux-wake-lock not found; Android may kill the node when the screen is off"; fi
fi

short_id() {
  ip4=$( { ifconfig 2>/dev/null || true; ip -4 addr 2>/dev/null || true; } | sed -n 's/.*inet \(addr:\)\{0,1\}\([0-9.]*\).*/\2/p' | grep -v '^127\.' | head -n1)
  if [ -n "$ip4" ]; then echo "${ip4##*.}"; return; fi
  b=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null | tr -cd 'a-f0-9' | cut -c1-6)
  [ -n "$b" ] && echo "$b"
}
if [ -z "$NAME" ]; then
  MODEL=$(getprop ro.product.model 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-' | sed 's/-*$//')
  SID=$(short_id || true)
  [ -n "$MODEL" ] || MODEL=$(uname -n 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-' | sed 's/-*$//')
  [ -n "$MODEL" ] && NAME="$MODEL${SID:+-$SID}"
fi
[ -n "$NAME" ] || die "could not determine host name; pass --name (e.g. a57, note9, pixel8)"
say "host $NAME, prefix $PREFIX_DIR"
run mkdir -p "$PREFIX_DIR/models"
# Vulkan: Termux's loader only sees llvmpipe; llama.cpp finds the real GPU (e.g. Xclipse 550)
# when LD_LIBRARY_PATH holds BOTH libvulkan.so and libvulkan.so.1 -> /system/lib64/libvulkan.so (#34).
VKDIR="$PREFIX_DIR/vulkan"
if [ -e /system/lib64/libvulkan.so ]; then
  run mkdir -p "$VKDIR"
  run ln -sf /system/lib64/libvulkan.so "$VKDIR/libvulkan.so"
  run ln -sf /system/lib64/libvulkan.so "$VKDIR/libvulkan.so.1"
else
  say "no /system/lib64/libvulkan.so; Vulkan offload unavailable, CPU only"
fi

if [ -d "$PREFIX_DIR/repo/.git" ]; then
  run git -C "$PREFIX_DIR/repo" pull --ff-only -q || say "warning: repo not fast-forwardable; left as is"
else
  run git clone -q --branch "$BRANCH" "$REPO_URL" "$PREFIX_DIR/repo"
fi

REPO="$PREFIX_DIR/repo"
SELF_REPO=$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd || true)
MTMP=""
if [ -f "$REPO/scripts/host_measure.py" ]; then MREPO="$REPO"
elif [ "$DRY" = 1 ] && [ -n "$SELF_REPO" ] && [ -f "$SELF_REPO/scripts/host_measure.py" ]; then MREPO="$SELF_REPO"
elif [ "$DRY" = 1 ] && command -v curl >/dev/null 2>&1; then
  # Dry run has no clone; fetch the read-only measurer + graph into a temp dir and delete it after.
  MTMP=$(mktemp -d "${TMPDIR:-${PREFIX:-}/tmp}/familia-measure.XXXXXX" 2>/dev/null || true)
  if [ -n "$MTMP" ] && mkdir -p "$MTMP/scripts" && curl -fsSL "$RAW_URL/$BRANCH/scripts/host_measure.py" -o "$MTMP/scripts/host_measure.py" \
     && curl -fsSL "$RAW_URL/$BRANCH/graph.yaml" -o "$MTMP/graph.yaml"; then MREPO="$MTMP"
  else MREPO=""; say "warning: could not fetch host_measure.py from $BRANCH"; fi
else MREPO=""; fi
if [ -n "$MREPO" ]; then
  MF=""; [ "$DRY" = 1 ] && MF=--dry-run
  python3 "$MREPO/scripts/host_measure.py" --name "$NAME" --kind phone --reserve-mib "$RESERVE_MIB" --graph "$MREPO/graph.yaml" $MF $FORCE_HOST || say "warning: host measurement failed"
  if [ "$DRY" != 1 ]; then
    python3 -c 'import yaml' 2>/dev/null && { python3 "$REPO/scripts/validate_graph.py" --no-files "$REPO/graph.yaml" || say "warning: graph validation reported problems"; }
  fi
else
  say "warning: host_measure.py unavailable; host not measured"
fi
[ -n "$MTMP" ] && rm -rf "$MTMP"

LAUNCH="${PREFIX:-/data/data/com.termux/files/usr}/bin/familia-start"
if [ "$DRY" = 1 ]; then say "[dry-run] write $LAUNCH"
else
  cat > "$LAUNCH" <<EOS
#!/data/data/com.termux/files/usr/bin/sh
# generated by familia install/termux/install.sh
: "\${FAMILIA_MODEL:?set FAMILIA_MODEL to a GGUF path or a name in $PREFIX_DIR/models}"
M="\$FAMILIA_MODEL"; [ -f "\$M" ] || M="$PREFIX_DIR/models/\$FAMILIA_MODEL"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
VK="$VKDIR"; NGL="\${FAMILIA_NGL:-0}"
if [ -e /system/lib64/libvulkan.so ]; then
  mkdir -p "\$VK"
  ln -sf /system/lib64/libvulkan.so "\$VK/libvulkan.so"
  ln -sf /system/lib64/libvulkan.so "\$VK/libvulkan.so.1"
  export LD_LIBRARY_PATH="\$VK\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
  NGL="\${FAMILIA_NGL:-99}"
fi
exec llama-server -m "\$M" -ngl "\$NGL" --host "\${FAMILIA_BIND:-127.0.0.1}" --port "\${FAMILIA_PORT:-9941}" -c "\${FAMILIA_CTX:-2048}" \${FAMILIA_EXTRA:-}
EOS
  chmod +x "$LAUNCH"
fi
if [ "$SSHD" = 1 ]; then
  run sshd
  say "sshd on port 8022 (key auth: add your key to ~/.ssh/authorized_keys; set a password with passwd only if you want one)"
fi
if [ -d "$HOME/.termux/boot" ]; then
  say "Termux:Boot detected; to autostart, create $BOOT that exports FAMILIA_MODEL and runs familia-start"
fi
say "done. Put GGUFs in $PREFIX_DIR/models; start: FAMILIA_MODEL=x.gguf familia-start"
