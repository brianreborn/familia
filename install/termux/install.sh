#!/data/data/com.termux/files/usr/bin/sh
# familia one-click installer: Android via Termux (F-Droid or GitHub build, not Play Store).
# Usage: sh install/termux/install.sh [flags]   (flags below)
# Add-ons must match Termux's signing key: with Termux from GitHub releases, get Termux:API from
#   https://github.com/termux/termux-api/releases (the termux-api pkg alone is not enough; termux-battery-status hangs).
#   p=familia                                         && \
#   o=brianreborn                                     && \
#   h=raw.githubusercontent.com                       && \
#   u=https://$h/$o/$p/main/install/termux/install.sh && \
#   curl -fsSLo install-$p.sh $u                      && \
#   sh        ./install-$p.sh
#   one line:
#   p=familia && o=brianreborn && h=raw.githubusercontent.com && u=https://$h/$o/$p/main/install/termux/install.sh && curl -fsSLo install-$p.sh $u && sh ./install-$p.sh
# Runtime comes from Termux's own `llama-cpp` package (pkg verifies package
# signatures/hashes), so no unverified binary is downloaded here.
# Flags: --dry-run  --uninstall [--purge]  --name NAME  --sshd (install+start openssh)
# familia-start: loopback by default; FAMILIA_BIND=<non-loopback> requires FAMILIA_API_KEY_FILE (mode 0600, Termux $HOME, not /sdcard).
#        --yes (accept the license review; summary still printed)  --accept-unknown
#        --no-runtime  --force-host  --no-wakelock
#        --branch BRANCH  select the familia branch (default: checkout branch, else main)
#        --no-path (do not write the $PREFIX/bin/familia shim; scripts/install-cli.sh)
#   --name defaults to <model>-<last IPv4 octet> (or <model>-<boot_id prefix>), unique per phone;
#          interactive installs prompt with that value as the default.
# Example: sh install/termux/install.sh --dry-run
set -eu

PREFIX_DIR=${FAMILIA_PREFIX:-$HOME/familia}
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
# Phones: Android + apps leave only ~2-2.6 GiB free on a 7.4 GiB A57 (docs/ram-safety.md); policy, not measured.
RESERVE_MIB=${FAMILIA_RESERVE_MIB:-5120}
RAW_URL=${FAMILIA_RAW_URL:-https://raw.githubusercontent.com/brianreborn/familia}
DRY=0; UNINSTALL=0; PURGE=0; NAME=""; SSHD=0; RUNTIME=1; FORCE_HOST=""; WAKE=1; NOPATH=0

say() { echo "familia-termux: $*" >&2; }
die() { say "error: $*"; exit 1; }
run() { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --branch) shift; [ -n "${1:-}" ] || die "--branch needs a branch name"; BRANCH=$1; SELECT_BRANCH=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --purge) PURGE=1 ;;
    --name) shift; NAME=${1:-} ;;
    --sshd) SSHD=1 ;;
    --no-runtime) RUNTIME=0 ;;
    --force-host) FORCE_HOST=--force ;;
    --no-wakelock) WAKE=0 ;;
    --no-path) NOPATH=1 ;;
    --yes|-y) FAMILIA_ACCEPT_LICENSES=yes; export FAMILIA_ACCEPT_LICENSES ;;
    --accept-unknown) FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes; export FAMILIA_ACCEPT_UNKNOWN_LICENSES ;;
    -h|--help) sed -n '2,14p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//' || true; exit 0 ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
  shift
done

git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || die "invalid branch name: $BRANCH"

if [ -z "${TERMUX_VERSION:-}" ] && [ ! -d /data/data/com.termux ]; then
  [ "$DRY" = 1 ] || die "not running inside Termux (use install/linux/install.sh on desktop Linux)"
  say "not in Termux; continuing because --dry-run"
fi
BOOT="$HOME/.termux/boot/familia-node.sh"

if [ "$UNINSTALL" = 1 ]; then
  run rm -f "$BOOT" "$PREFIX/bin/familia-start" 2>/dev/null || true
  if [ -f "$PREFIX_DIR/repo/scripts/install-cli.sh" ]; then  # the familia shim, exactly what it recorded
    if [ "$DRY" = 1 ]; then sh "$PREFIX_DIR/repo/scripts/install-cli.sh" uninstall --dry-run
    else sh "$PREFIX_DIR/repo/scripts/install-cli.sh" uninstall --yes; fi
  fi
  if [ "$PURGE" = 1 ]; then run rm -rf "$PREFIX_DIR"
  else run rm -rf "$PREFIX_DIR/repo"; say "kept $PREFIX_DIR/models (use --purge)"; fi
  say "left Termux packages (git python llama-cpp openssh) installed; remove with pkg uninstall if wanted"
  say "uninstalled"; exit 0
fi

# Default Termux packages (Brian 2026-10-27): getconf + pytest were missing on phones.
# Full list / --profile build: sh install/deps.sh or install/termux/deps.sh
PKGS="git python getconf"
[ "$RUNTIME" = 1 ] && PKGS="$PKGS llama-cpp"
[ "$SSHD" = 1 ] && PKGS="$PKGS openssh"
# shellcheck disable=SC2086 # word list
run pkg install -y $PKGS
run pip install --quiet pyyaml || say "warning: pyyaml not installed; graph validation skipped"
# pytest: prefer Termux python-pytest when the index has it; else pip (scripts/run-tests.sh also vendors into .cache/pylib).
if [ "$DRY" = 1 ]; then
  say "[dry-run] would ensure pytest (pkg python-pytest or pip install pytest)"
elif python -m pytest --version >/dev/null 2>&1 || command -v pytest >/dev/null 2>&1; then
  :
elif pkg search python-pytest 2>/dev/null | grep -q '^python-pytest'; then
  run pkg install -y python-pytest || run pip install --quiet pytest || say "warning: pytest not installed"
else
  run pip install --quiet pytest || say "warning: pytest not installed (pip); tests can still use scripts/run-tests.sh"
fi

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
  if [ -n "$NAME" ] && [ -t 0 ]; then
    printf 'Host name for graph.yaml [%s]: ' "$NAME" >&2
    IFS= read -r ANSWER || ANSWER=""
    [ -z "$ANSWER" ] || NAME=$ANSWER
  fi
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
  if [ "$SELECT_BRANCH" = 1 ]; then
    if [ "$DRY" = 1 ]; then
      say "[dry-run] would switch $PREFIX_DIR/repo to track origin/$BRANCH and fast-forward only"
    else
      git -C "$PREFIX_DIR/repo" fetch -q origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" ||
        die "could not fetch origin/$BRANCH"
      if git -C "$PREFIX_DIR/repo" show-ref --verify --quiet "refs/heads/$BRANCH"; then
        run git -C "$PREFIX_DIR/repo" switch "$BRANCH"
      else
        run git -C "$PREFIX_DIR/repo" switch --track -c "$BRANCH" "origin/$BRANCH"
      fi
      run git -C "$PREFIX_DIR/repo" branch --set-upstream-to="origin/$BRANCH" "$BRANCH"
      run git -C "$PREFIX_DIR/repo" merge --ff-only "origin/$BRANCH" ||
        die "repo branch $BRANCH could not be fast-forwarded; local changes were preserved"
    fi
  else
    run git -C "$PREFIX_DIR/repo" pull --ff-only -q || say "warning: repo not fast-forwardable; left as is"
  fi
else
  run git clone -q --branch "$BRANCH" "$REPO_URL" "$PREFIX_DIR/repo"
fi

REPO="$PREFIX_DIR/repo"
# Licenses before anything else is downloaded (docs/licenses.md).
if [ "$DRY" = 1 ]; then
  say "[dry-run] would show the license review: python $REPO/scripts/licenses.py gate"
elif [ -f "$REPO/scripts/licenses.py" ]; then
  python "$REPO/scripts/licenses.py" gate || die "licenses not accepted; nothing else was downloaded. Review: python $REPO/scripts/licenses.py review (or re-run with --yes, plus --accept-unknown)"
fi
# Every pinned part to its pin, together (scripts/sync_pins.py); again after each later git pull.
if [ "$DRY" = 1 ]; then
  say "[dry-run] would sync the pinned parts: python $REPO/scripts/sync_pins.py"
elif [ -f "$REPO/scripts/sync_pins.py" ]; then
  python "$REPO/scripts/sync_pins.py" --root "$REPO" || die "the pinned parts could not be synced (see above)"
  python "$REPO/scripts/sync_pins.py" --root "$REPO" --install-hooks || true
fi
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
NPSPEC=numpy; [ -n "$MREPO" ] && [ -f "$MREPO/scripts/cpu_level.py" ] && NPSPEC=$(python "$MREPO/scripts/cpu_level.py" --numpy-spec 2>/dev/null || echo numpy)
python -c 'import numpy' 2>/dev/null || run pip install --quiet "$NPSPEC" || say "note: numpy not installed (optional; pkg install python-numpy)"
else MREPO=""; fi
if [ -n "$MREPO" ]; then
  MF=""; [ "$DRY" = 1 ] && MF=--dry-run
  python3 "$MREPO/scripts/host_measure.py" --name "$NAME" --kind phone --reserve-mib "$RESERVE_MIB" --graph "$MREPO/graph.yaml" $MF $FORCE_HOST || say "warning: host measurement failed"
  if [ "$DRY" != 1 ] && [ -f "$REPO/scripts/hostname_pin.py" ]; then
    python3 "$REPO/scripts/hostname_pin.py" set "$NAME" || say "warning: could not write hostname pin"
  fi
  if [ "$DRY" != 1 ]; then
    python3 -c 'import yaml' 2>/dev/null && { python3 "$REPO/scripts/validate_graph.py" --no-files --graph "$REPO/graph.yaml" || say "warning: graph validation reported problems"; }
  fi
else
  say "warning: host_measure.py unavailable; host not measured"
fi
[ -n "$MTMP" ] && rm -rf "$MTMP"

LAUNCH="${PREFIX:-/data/data/com.termux/files/usr}/bin/familia-start"
# Phones always require an API key (Brian 2026-11-02), loopback included: generate a 0600 key
# in ~/.config/familia/api.key once; the launcher uses it unless FAMILIA_API_KEY_FILE is set.
FAMILIA_KEY_DEFAULT="$HOME/.config/familia/api.key"
if [ "$DRY" = 1 ]; then say "[dry-run] generate $FAMILIA_KEY_DEFAULT (0600) if missing"
elif [ ! -e "$FAMILIA_KEY_DEFAULT" ] && [ ! -L "$FAMILIA_KEY_DEFAULT" ]; then
  if ! { ( umask 077; mkdir -p "$HOME/.config/familia" && head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$FAMILIA_KEY_DEFAULT.tmp.$$" ) \
    && chmod 600 "$FAMILIA_KEY_DEFAULT.tmp.$$" && mv -f "$FAMILIA_KEY_DEFAULT.tmp.$$" "$FAMILIA_KEY_DEFAULT"; }; then
    say "error: could not generate $FAMILIA_KEY_DEFAULT"; exit 1
  fi
  say "generated API key $FAMILIA_KEY_DEFAULT (0600); clients send Authorization: Bearer <key>"
fi
if [ "$DRY" = 1 ]; then say "[dry-run] write $LAUNCH"
else
  cat > "$LAUNCH" <<EOS
#!/data/data/com.termux/files/usr/bin/sh
# generated by familia install/termux/install.sh
: "\${FAMILIA_MODEL:?set FAMILIA_MODEL to a GGUF path or a name in $PREFIX_DIR/models}"
M="\$FAMILIA_MODEL"; [ -f "\$M" ] || M="$PREFIX_DIR/models/\$FAMILIA_MODEL"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
echo "familia-start: logs: this terminal (stdout/stderr)" >&2
VK="$VKDIR"; NGL="\${FAMILIA_NGL:-0}"
if [ -e /system/lib64/libvulkan.so ]; then
  mkdir -p "\$VK"
  ln -sf /system/lib64/libvulkan.so "\$VK/libvulkan.so"
  ln -sf /system/lib64/libvulkan.so "\$VK/libvulkan.so.1"
  export LD_LIBRARY_PATH="\$VK\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
  NGL="\${FAMILIA_NGL:-99}"
fi
# Loopback by default. A key file (0600) is required on EVERY bind, loopback included (other
# Termux apps / adb on the same phone can reach 127.0.0.1).
# BEGIN familia-bind-check (extracted by tests/test_termux_bind_check.py)
is_loopback() {
  case "\$1" in
    localhost|::1|'[::1]') return 0 ;;
    127.*) ;;
    *) return 1 ;;
  esac
  # Strict dotted quad 127.a.b.c, decimal octets 0-255 (127.example / 127.0.0.1.evil are not loopback).
  _ip="\$1"; _n=0; _rest="\$_ip."
  while [ -n "\$_rest" ]; do
    _o="\${_rest%%.*}"; _rest="\${_rest#*.}"; _n=\$((_n+1))
    case "\$_o" in ''|*[!0-9]*) return 1 ;; esac
    [ \${#_o} -le 3 ] && [ "\$_o" -le 255 ] || return 1
  done
  [ "\$_n" -eq 4 ]
}
familia_key_args() { # sets positional-safe FAMILIA_KF or exits
  B="\${FAMILIA_BIND:-127.0.0.1}"; FAMILIA_KF=""
  # F-9: llama-server --host takes a bare IPv6 address: [::1] -> ::1.
  [ "\$B" = '[::1]' ] && B=::1
  # Brian 2026-11-02: key required on every bind, loopback included.
  KF="\${FAMILIA_API_KEY_FILE:-\$HOME/.config/familia/api.key}"
  [ -e "\$KF" ] || [ -L "\$KF" ] || { echo "familia-start: API key file \$KF missing; a key is required on every bind (loopback included); re-run install or set FAMILIA_API_KEY_FILE to a 0600 key file" >&2; exit 2; }
  [ -L "\$KF" ] && { echo "familia-start: \$KF is a symlink; refusing" >&2; exit 2; }
  # F-7: resolve first (a symlinked parent dir must not dodge the shared-storage check).
  _r=\$(realpath -e -- "\$KF" 2>/dev/null) || { echo "familia-start: \$KF does not resolve; refusing" >&2; exit 2; }
  KF="\$_r"
  # Same list as green-roomz config/shared-storage-prefixes.txt (duplicated on purpose: the
  # launcher is standalone; tests/test_termux_bind_check.py keeps them in sync).
  case "\$KF" in /storage|/storage/*|/sdcard|/sdcard/*|/mnt/sdcard|/mnt/sdcard/*|/mnt/user|/mnt/user/*|/mnt/media_rw|/mnt/media_rw/*|/data/media|/data/media/*|/data/local/tmp|/data/local/tmp/*) echo "familia-start: \$KF (resolved) is on shared/adb storage; refusing" >&2; exit 2 ;; esac
  [ -f "\$KF" ] || { echo "familia-start: \$KF is not a regular file" >&2; exit 2; }
  case "\$(stat -c %a "\$KF" 2>/dev/null)" in 600|400) ;; *) echo "familia-start: \$KF must be mode 0600" >&2; exit 2 ;; esac
  [ "\$(stat -c %u "\$KF" 2>/dev/null)" = "\$(id -u)" ] || { echo "familia-start: \$KF is not owned by you" >&2; exit 2; }
  FAMILIA_KF="\$KF"
}
# F-6 + Boundary Reviewer items: FAMILIA_EXTRA (whitespace-split) and the launcher's own argv ("\$@") are checked
# token by token. If any token would override bind, port, auth, TLS or a path
# (--host* --port* --api-key* --ssl* --path*) the whole launch is refused, never stripped.
# set -f is turned on here and deliberately LEFT ON for the rest of the launcher: the exec
# below expands \${FAMILIA_EXTRA} unquoted and must not glob. Nothing after this relies on globbing.
familia_extra_check() {
  set -f
  for _t in \${FAMILIA_EXTRA:-} "\$@"; do
    case "\$_t" in
      --host*|--port*|--api-key*|--ssl*|--path*) echo "familia-start: token \$_t (FAMILIA_EXTRA or argv) would override bind/port/auth/TLS/path; refusing" >&2; exit 2 ;;
    esac
  done
}
# END familia-bind-check
familia_key_args
familia_extra_check "\$@"
set --
[ -n "\$FAMILIA_KF" ] || { echo "familia-start: no API key; refusing" >&2; exit 2; }
set -- --api-key-file "\$FAMILIA_KF"
# Defaults from the 2026-10-10 A57 sweep (#34): 3 threads, flash-attn on; -ngl 99 on Vulkan (CPU ngl 0 on 0.6.0 collapses to <1 t/s tg).
exec llama-server -m "\$M" -ngl "\$NGL" -t "\${FAMILIA_THREADS:-3}" -fa "\${FAMILIA_FA:-on}" --host "\$B" --port "\${FAMILIA_PORT:-9941}" -c "\${FAMILIA_CTX:-2048}" "\$@" \${FAMILIA_EXTRA:-}
EOS
  chmod +x "$LAUNCH"
fi
# BEGIN familia-sshd-verify (extracted by tests)
# F-8: after writing the config, ask sshd itself for the effective settings (no restart here).
familia_sshd_verify() { # cfg
  # F-8b: evaluate with a connection spec so Match blocks apply (sshd -T alone skips them).
  _spec="user=$(id -un),addr=127.0.0.1,host=localhost"
  _eff=$(sshd -T -C "$_spec" -f "$1" 2>&1) || { echo "error: sshd -T -C $_spec -f $1 failed: $_eff; not starting sshd" >&2; return 1; }
  printf '%s\n' "$_eff" | grep -qx 'passwordauthentication no' || { echo "error: sshd -T: passwordauthentication is not 'no'; not starting sshd" >&2; return 1; }
  printf '%s\n' "$_eff" | grep -qx 'kbdinteractiveauthentication no' || { echo "error: sshd -T: kbdinteractiveauthentication is not 'no'; not starting sshd" >&2; return 1; }
  # Any Match block that turns an *Authentication method on (other users/addrs) is refused.
  # PubkeyAuthentication yes is the intended method and is allowed.
  _m=$(awk 'tolower($1)=="match"{m=1;next} m && tolower($1) ~ /authentication$/ && tolower($1)!="pubkeyauthentication" && tolower($2)=="yes"{print NR": "$0}' "$1") \
    || { echo "error: cannot read $1; not starting sshd" >&2; return 1; }
  [ -z "$_m" ] || { echo "error: Match block in $1 enables auth ($_m); not starting sshd" >&2; return 1; }
}
# END familia-sshd-verify
if [ "$SSHD" = 1 ]; then
  # Key auth only: disable passwords before sshd starts (idempotent).
  SSHD_CFG="${PREFIX:-/data/data/com.termux/files/usr}/etc/ssh/sshd_config"
  if [ "$DRY" = 1 ]; then say "[dry-run] set PasswordAuthentication no in $SSHD_CFG"
  else
    [ -f "$SSHD_CFG" ] || { say "error: $SSHD_CFG missing; not starting sshd"; exit 1; }
    # POSIX: no sed -i. Rewrite via temp + mv (Platform standing rule).
    _sshd_tmp=$(mktemp "${TMPDIR:-${PREFIX:-}/tmp}/familia-sshd.XXXXXX") \
      || { say "error: mktemp failed; not starting sshd"; exit 1; }
    sed -e 's/^[[:space:]#]*PasswordAuthentication[[:space:]].*$/PasswordAuthentication no/' \
        -e 's/^[[:space:]#]*KbdInteractiveAuthentication[[:space:]].*$/KbdInteractiveAuthentication no/' \
        "$SSHD_CFG" > "$_sshd_tmp" \
      || { rm -f "$_sshd_tmp"; say "error: sed rewrite of $SSHD_CFG failed"; exit 1; }
    mv "$_sshd_tmp" "$SSHD_CFG" || { rm -f "$_sshd_tmp"; say "error: mv onto $SSHD_CFG failed"; exit 1; }
    grep -q '^PasswordAuthentication no$' "$SSHD_CFG" || printf '\nPasswordAuthentication no\n' >> "$SSHD_CFG"
    grep -q '^KbdInteractiveAuthentication no$' "$SSHD_CFG" || printf 'KbdInteractiveAuthentication no\n' >> "$SSHD_CFG"
    familia_sshd_verify "$SSHD_CFG" || exit 1
  fi
  # A running sshd keeps its old config; it is not restarted here.
  run sshd
  say "sshd on port 8022 (key auth only; PasswordAuthentication no). Add your key to ~/.ssh/authorized_keys"
fi
if [ -d "$HOME/.termux/boot" ]; then
  say "Termux:Boot detected; to autostart, create $BOOT that exports FAMILIA_MODEL and runs familia-start"
fi
# `familia` on PATH: Termux's $PREFIX/bin is already on PATH, so this is just the 2-line shim.
if [ "$NOPATH" = 1 ]; then say "--no-path: no familia shim (later: sh $REPO/scripts/install-cli.sh)"
elif [ -f "$REPO/scripts/install-cli.sh" ]; then
  CF=""; [ "$DRY" = 1 ] && CF=--dry-run
  sh "$REPO/scripts/install-cli.sh" $CF | sed 's/^/  /' >&2 || say "warning: could not write the familia shim"
else say "[dry-run] write the familia shim: sh $REPO/scripts/install-cli.sh"; fi
# Charm gum (pkg or Charm Linux binary → $PREFIX/bin). Soft-fail.
if [ -f "$REPO/scripts/install-gum.sh" ]; then
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would ensure gum: sh $REPO/scripts/install-gum.sh --dry-run"
  else
    sh "$REPO/scripts/install-gum.sh" --yes || say "warning: gum not installed; retry: sh $REPO/scripts/install-gum.sh"
  fi
fi
say "done. Put GGUFs in $PREFIX_DIR/models; start: FAMILIA_MODEL=x.gguf familia-start"
say "what now: run $REPO/familia for the Charm/gum home (Talk to the protomodel). Quick start: $REPO/QUICKSTART.md"
