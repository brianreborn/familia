#!/data/data/com.termux/files/usr/bin/sh
# One-tap Android path: licenses -> cbl prebuilt runtime -> default phone model -> Hermes webapp.
# Webapp-first: opens the Hermes webapp URL on device. Hermes Desktop + Office 3D run on a
# Linux/macOS host; see docs/android-hermes.md.
# Usage:
#   sh install/termux/install-hermes-android.sh [--dry-run] [--yes] [--accept-unknown]
#                                               [--skip-install] [--no-open]
# Env:
#   FAMILIA_ACCEPT_LICENSES=yes / FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes
#   FAMILIA_PHONE_MODEL / FAMILIA_PHONE_MODEL_TIER / FAMILIA_RESERVE_MIB
#   FAMILIA_RUNTIME=cbl (default) | pkg
#   INSTALL_ACK=yes          alias for license --yes (proto compatibility)
# Never pipe a download into a shell. No sudo. Nothing is pushed to phones from this script alone.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
DRY=0
YES=0
UNK=0
SKIP_INSTALL=0
NO_OPEN=0
# Dolphin3 registry id (license llama3.1) — required minimum for the phone gate.
DOLPHIN_DB=RavichandranJ--Dolphin3-Cyber-8B-GGUF--Dolphin3.0-Llama3.1-8B-abliterated.Q2_K

say() { printf 'familia-hermes-android: %s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --yes|-y) YES=1; FAMILIA_ACCEPT_LICENSES=yes; export FAMILIA_ACCEPT_LICENSES ;;
    --accept-unknown) UNK=1; FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes; export FAMILIA_ACCEPT_UNKNOWN_LICENSES ;;
    --skip-install) SKIP_INSTALL=1 ;;
    --no-open) NO_OPEN=1 ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
  shift
done

# Proto compatibility: INSTALL_ACK=yes means accept licenses non-interactively.
case "${INSTALL_ACK:-}" in yes|YES|Yes) YES=1; FAMILIA_ACCEPT_LICENSES=yes; export FAMILIA_ACCEPT_LICENSES ;; esac

if [ -z "${TERMUX_VERSION:-}" ] && [ ! -d /data/data/com.termux ]; then
  [ "$DRY" = 1 ] || die "not running inside Termux (use --dry-run to preview on a desktop)"
  say "not in Termux; continuing because --dry-run"
fi

# --- License gate: reuse scripts/licenses.py; force-include Dolphin3 + Llama 3.1 ---
GATE_ARGS="gate --add-model $DOLPHIN_DB --require-llama31"
[ "$YES" = 1 ] && GATE_ARGS="$GATE_ARGS --yes"
[ "$UNK" = 1 ] && GATE_ARGS="$GATE_ARGS --accept-unknown"
if [ "$DRY" = 1 ]; then
  say "[dry-run] would run: python $ROOT/scripts/licenses.py $GATE_ARGS"
else
  # shellcheck disable=SC2086
  python "$ROOT/scripts/licenses.py" $GATE_ARGS \
    || die "licenses not accepted; nothing else was started"
fi

# --- Base Termux install (cbl runtime by default) ---
INSTALL_ARGS=""
[ "$DRY" = 1 ] && INSTALL_ARGS="$INSTALL_ARGS --dry-run"
[ "$YES" = 1 ] && INSTALL_ARGS="$INSTALL_ARGS --yes"
[ "$UNK" = 1 ] && INSTALL_ARGS="$INSTALL_ARGS --accept-unknown"
if [ "$SKIP_INSTALL" = 1 ]; then
  say "skipping install/termux/install.sh (--skip-install)"
else
  # shellcheck disable=SC2086
  sh "$HERE/install.sh" $INSTALL_ARGS || die "install/termux/install.sh failed"
fi

# --- Default phone model by RAM ---
MODEL_JSON=$(python3 "$HERE/phone-model-default.py" --json 2>/dev/null || true)
if [ -z "$MODEL_JSON" ]; then
  # Desktop dry-run without /proc/meminfo: assume A57-class usable.
  MODEL_JSON=$(python3 "$HERE/phone-model-default.py" --ram-mib 7570 --json)
fi
MODEL=$(printf '%s' "$MODEL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["model"])')
TIER=$(printf '%s' "$MODEL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tier"])')
say "default phone model tier=$TIER model=$MODEL (override with FAMILIA_PHONE_MODEL)"

# --- Launch Hermes webapp ---
# Desktop + Office 3D: not on Android; connect the phone to a Linux/macOS host
# running Hermes Desktop with the office-3d plugin (docs/android-hermes.md).
HERMES="$ROOT/scripts/hermes.sh"
LAUNCH_CMD="$HERMES --client webapp --yes"
if [ "$DRY" = 1 ]; then
  say "[dry-run] would: FAMILIA_MODEL=$MODEL $LAUNCH_CMD"
  say "[dry-run] would open the one-use webapp URL via termux-open-url (unless --no-open)"
  say "Office 3D / Hermes Desktop: run on a Linux or macOS host; phone uses webapp chat."
  exit 0
fi

# Prefer exporting FAMILIA_MODEL so familia-start / hermes can resolve the GGUF.
export FAMILIA_MODEL="$MODEL"
say "starting Hermes webapp (client=webapp). Desktop+Office3D stay on a Linux/macOS host."
# Capture stderr for a URL; hermes may print a one-use link. We also try common local ports.
LOG=$(mktemp "${TMPDIR:-/tmp}/familia-hermes-webapp.XXXXXX")
# Do not fail the whole install if hermes is not yet on PATH / not pinned — report clearly.
set +e
# shellcheck disable=SC2086
sh $LAUNCH_CMD >"$LOG" 2>&1 &
HPID=$!
set -e
sleep 2
URL=$(sed -n -E 's/.*(https?:\/\/[^[:space:]]+).*/\1/p' "$LOG" | head -n 1 || true)
if [ -z "$URL" ]; then
  # Fallback: many hermes webapp builds listen on loopback; user can open manually.
  URL="http://127.0.0.1:8642/"
  say "no URL parsed from hermes output yet; trying default $URL (see $LOG)"
fi
say "webapp URL: $URL"
if [ "$NO_OPEN" = 1 ]; then
  say "--no-open: not launching a browser"
elif command -v termux-open-url >/dev/null 2>&1; then
  termux-open-url "$URL" || say "warning: termux-open-url failed for $URL"
else
  say "termux-open-url not found; open $URL in a browser (install Termux:API matching your Termux build)"
fi
say "done. Hermes Desktop + Office 3D: on a Linux/macOS host, install Hermes Desktop,"
say "  then: hermes plugins install office-3d && hermes plugins enable office-3d"
say "  Phone stays on webapp; optionally remote into that host later."
# Leave hermes running in background when launched; caller can manage the job.
if kill -0 "$HPID" 2>/dev/null; then
  say "hermes webapp pid $HPID (log $LOG)"
else
  say "hermes exited early; log: $LOG"
  sed 's/^/  | /' "$LOG" >&2 || true
fi
