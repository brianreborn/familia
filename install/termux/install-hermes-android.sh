#!/data/data/com.termux/files/usr/bin/sh
# One-tap Android path: licenses -> cbl prebuilt runtime -> default phone model ->
# familia-start (serves the chosen .gguf) -> Hermes webapp UI.
# Webapp-first: opens the Hermes webapp URL on device. Hermes Desktop + Office 3D run on a
# Linux/macOS host; see docs/android-hermes.md.
# Usage:
#   sh install/termux/install-hermes-android.sh [--dry-run] [--yes] [--accept-unknown]
#                                               [--skip-install] [--no-open] [--launch-only]
# Env:
#   FAMILIA_ACCEPT_LICENSES=yes / FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes
#   FAMILIA_PHONE_MODEL / FAMILIA_PHONE_MODEL_TIER / FAMILIA_RESERVE_MIB
#   FAMILIA_RUNTIME=cbl (default) | pkg
#   INSTALL_ACK=yes          alias for license --yes (proto compatibility; not used by the widget)
# Never pipe a download into a shell. No sudo. Widget taps must not pass --yes.
# The chosen GGUF is served by familia-start; Hermes webapp is the chat UI on top.
set -eu

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH='' cd -- "$HERE/../.." && pwd)
DRY=0
YES=0
UNK=0
SKIP_INSTALL=0
NO_OPEN=0
LAUNCH_ONLY=0
DOLPHIN_DB=RavichandranJ--Dolphin3-Cyber-8B-GGUF--Dolphin3.0-Llama3.1-8B-abliterated.Q2_K
PREFIX_DIR=${FAMILIA_PREFIX:-$HOME/familia}

say() { printf 'familia-hermes-android: %s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }

have_tty() { [ -t 0 ] && [ -t 1 ]; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --yes|-y) YES=1; FAMILIA_ACCEPT_LICENSES=yes; export FAMILIA_ACCEPT_LICENSES ;;
    --accept-unknown) UNK=1; FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes; export FAMILIA_ACCEPT_UNKNOWN_LICENSES ;;
    --skip-install) SKIP_INSTALL=1 ;;
    --launch-only) LAUNCH_ONLY=1; SKIP_INSTALL=1 ;;
    --no-open) NO_OPEN=1 ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
  shift
done

case "${INSTALL_ACK:-}" in yes|YES|Yes) YES=1; FAMILIA_ACCEPT_LICENSES=yes; export FAMILIA_ACCEPT_LICENSES ;; esac

if [ -z "${TERMUX_VERSION:-}" ] && [ ! -d /data/data/com.termux ]; then
  [ "$DRY" = 1 ] || die "not running inside Termux (use --dry-run to preview on a desktop)"
  say "not in Termux; continuing because --dry-run"
fi

# --- Default phone model by RAM (needed before the license gate) ---
MODEL_JSON=$(python3 "$HERE/phone-model-default.py" --json 2>/dev/null || true)
if [ -z "$MODEL_JSON" ]; then
  MODEL_JSON=$(python3 "$HERE/phone-model-default.py" --ram-mib 7570 --json)
fi
MODEL=$(printf '%s' "$MODEL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["model"])')
TIER=$(printf '%s' "$MODEL_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tier"])')
say "default phone model tier=$TIER model=$MODEL (override with FAMILIA_PHONE_MODEL)"

SELECTED_DB=$(python3 -c '
import os, sys, yaml
root = sys.argv[1]; mid = sys.argv[2]
g = yaml.safe_load(open(os.path.join(root, "graph.yaml"), encoding="utf-8"))
m = (g.get("models") or {}).get(mid) or {}
db = m.get("db") or ""
if not db:
    sys.stderr.write("familia-hermes-android: graph model %r missing db\n" % mid)
    sys.exit(1)
print(db)
' "$ROOT" "$MODEL") || die "could not resolve registry db for model $MODEL"

GATE_BASE="--add-model $SELECTED_DB --add-model $DOLPHIN_DB --require-llama31"

# --- License gate ---
# Launch-only: skip the gate when the current selection is already accepted.
# If the selection changed: interactive accept on a TTY; refuse clearly with no TTY.
# Widget taps never pass --yes, so a changed selection always needs a terminal.
run_license_gate() {
  GATE_ARGS="gate $GATE_BASE"
  [ "$YES" = 1 ] && GATE_ARGS="$GATE_ARGS --yes"
  [ "$UNK" = 1 ] && GATE_ARGS="$GATE_ARGS --accept-unknown"
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would run: python $ROOT/scripts/licenses.py $GATE_ARGS"
    return 0
  fi
  # shellcheck disable=SC2086
  python "$ROOT/scripts/licenses.py" $GATE_ARGS \
    || die "licenses not accepted; nothing else was started"
}

if [ "$LAUNCH_ONLY" = 1 ] && [ "$DRY" != 1 ]; then
  # shellcheck disable=SC2086
  if python "$ROOT/scripts/licenses.py" check --quiet $GATE_BASE; then
    say "launch-only: license selection unchanged and accepted; skipping gate"
  else
    say "license selection changed or not yet accepted"
    if [ "$YES" = 1 ]; then
      run_license_gate
    elif have_tty; then
      say "opening interactive license review (widget taps do not auto-accept)"
      run_license_gate
    else
      die "licenses not accepted (selection changed or first run). Re-run install/termux/install-hermes-android.sh in a Termux terminal and accept there. Widget taps do not pass --yes / do not auto-accept licenses."
    fi
  fi
elif [ "$DRY" = 1 ]; then
  say "[dry-run] would run: python $ROOT/scripts/licenses.py gate $GATE_BASE${YES:+ --yes}${UNK:+ --accept-unknown}"
else
  if [ "$YES" != 1 ] && ! have_tty; then
    # Still try check: if already accepted, proceed; else refuse.
    # shellcheck disable=SC2086
    if python "$ROOT/scripts/licenses.py" check --quiet $GATE_BASE; then
      say "licenses already accepted; continuing without a TTY"
    else
      die "licenses not accepted and no TTY for interactive review. Run this script in a Termux terminal (or pass --yes only from an interactive install you control). Widget taps do not auto-accept licenses."
    fi
  else
    run_license_gate
  fi
fi

# --- Base Termux install (cbl runtime by default) ---
if [ "$LAUNCH_ONLY" = 1 ]; then
  say "launch-only: skipping install/termux/install.sh"
elif [ "$SKIP_INSTALL" = 1 ]; then
  say "skipping install/termux/install.sh (--skip-install)"
else
  INSTALL_ARGS=""
  [ "$DRY" = 1 ] && INSTALL_ARGS="$INSTALL_ARGS --dry-run"
  [ "$YES" = 1 ] && INSTALL_ARGS="$INSTALL_ARGS --yes"
  [ "$UNK" = 1 ] && INSTALL_ARGS="$INSTALL_ARGS --accept-unknown"
  # shellcheck disable=SC2086
  sh "$HERE/install.sh" $INSTALL_ARGS || die "install/termux/install.sh failed"
fi

# --- Download / resolve the chosen GGUF (pinned hashes) ---
# Launch-only: --cheap skips full re-hash when marker size+mtime+sha are unchanged.
FETCH_ARGS="--model $MODEL --prefix $PREFIX_DIR"
[ "$DRY" = 1 ] && FETCH_ARGS="$FETCH_ARGS --dry-run"
[ "$LAUNCH_ONLY" = 1 ] && [ "$DRY" != 1 ] && FETCH_ARGS="$FETCH_ARGS --cheap"
# shellcheck disable=SC2086
MODEL_PATH=$(python3 "$HERE/fetch-phone-model.py" $FETCH_ARGS) \
  || die "could not fetch/verify phone model $MODEL"
say "model path: $MODEL_PATH"

# Resolve familia-start launcher.
FAMILIA_START=""
for cand in \
    "${PREFIX:-/data/data/com.termux/files/usr}/bin/familia-start" \
    "$PREFIX_DIR/bin/familia-start" \
    "$(command -v familia-start 2>/dev/null || true)"
do
  if [ -n "$cand" ] && [ -x "$cand" ]; then FAMILIA_START=$cand; break; fi
done

HERMES="$ROOT/scripts/hermes.sh"
if [ "$DRY" = 1 ]; then
  say "[dry-run] would: FAMILIA_MODEL=$MODEL_PATH familia-start (serves the chosen .gguf on loopback${FAMILIA_START:+ via $FAMILIA_START})"
  say "[dry-run] would: FAMILIA_MODEL=$MODEL_PATH bash $HERMES --client webapp --yes (webapp UI)"
  say "[dry-run] would poll hermes output for a webapp URL (no sleep+guessed port)"
  say "[dry-run] would open the one-use webapp URL via termux-open-url (unless --no-open)"
  say "Office 3D / Hermes Desktop: run on a Linux or macOS host; phone uses webapp chat."
  exit 0
fi

export FAMILIA_MODEL="$MODEL_PATH"

# --- Serve the GGUF via familia-start (this is what loads the model) ---
if [ -z "$FAMILIA_START" ]; then
  die "familia-start not found; run install/termux/install.sh first (it installs the launcher that serves the GGUF)"
fi
say "starting familia-start to serve $MODEL_PATH"
FS_LOG=$(mktemp "${TMPDIR:-/tmp}/familia-start.XXXXXX")
set +e
"$FAMILIA_START" >"$FS_LOG" 2>&1 &
FSPID=$!
set -e
# Readiness poll on the default familia-start port (9941).
PORT="${FAMILIA_PORT:-9941}"
i=0
READY=0
while [ "$i" -lt 30 ]; do
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/health" 2>/dev/null \
       || curl -fsS -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/v1/models" 2>/dev/null; then
      READY=1
      break
    fi
  fi
  if ! kill -0 "$FSPID" 2>/dev/null; then
    say "familia-start exited early; log:"
    sed 's/^/  | /' "$FS_LOG" >&2 || true
    rm -f "$FS_LOG"
    die "familia-start failed to serve the model"
  fi
  sleep 1
  i=$((i + 1))
done
if [ "$READY" = 1 ]; then
  say "familia-start ready on 127.0.0.1:${PORT} (pid $FSPID)"
else
  say "warning: familia-start not ready after ${i}s; continuing to Hermes webapp (pid $FSPID)"
fi
rm -f "$FS_LOG"

# --- Hermes webapp UI (talks to the local stack; does not load the GGUF itself) ---
say "starting Hermes webapp UI (client=webapp). Desktop+Office3D stay on a Linux/macOS host."
LOG=$(mktemp "${TMPDIR:-/tmp}/familia-hermes-webapp.XXXXXX")
cleanup_log() { rm -f "$LOG"; }
trap cleanup_log EXIT

set +e
bash "$HERMES" --client webapp --yes >"$LOG" 2>&1 &
HPID=$!
set -e

redact_log_tail() {
  # Print last 40 lines; redact bearer tokens and one-time / tokenized URLs.
  tail -n 40 "$1" 2>/dev/null | sed -E \
    -e 's/[Bb]earer[[:space:]]+[A-Za-z0-9._~+\/=\-]+/[REDACTED_BEARER]/g' \
    -e 's/(token|access_token|api[_-]?key|one[_-]?time)(=|":[[:space:]]*")[^[:space:]&"]+/\1\2[REDACTED]/g' \
    -e 's|(https?://[^[:space:]]*[Tt]oken[^[:space:]]*)|[REDACTED_URL]|g' \
    -e 's|(https?://[^[:space:]]*one[_-]?time[^[:space:]]*)|[REDACTED_URL]|g' \
    -e 's|(https?://[^[:space:]]*[?][^[:space:]]*key=[^[:space:]]*)|[REDACTED_URL]|g' \
    | sed 's/^/  | /' >&2 || true
}

URL=""
i=0
MAX=60
while [ "$i" -lt "$MAX" ]; do
  if [ -f "$LOG" ]; then
    URL=$(sed -n -E 's/.*(https?:\/\/[^[:space:]\"'\'']+).*/\1/p' "$LOG" | head -n 1 || true)
    if [ -n "$URL" ]; then
      break
    fi
  fi
  if ! kill -0 "$HPID" 2>/dev/null; then
    break
  fi
  HPORT=$(sed -n -E 's/.*[Ll]isten[^0-9]*([0-9]{2,5}).*/\1/p' "$LOG" 2>/dev/null | head -n 1 || true)
  if [ -n "$HPORT" ] && command -v curl >/dev/null 2>&1; then
    if curl -fsS -o /dev/null --max-time 1 "http://127.0.0.1:${HPORT}/" 2>/dev/null \
       || curl -fsS -o /dev/null --max-time 1 "http://127.0.0.1:${HPORT}/health" 2>/dev/null; then
      URL="http://127.0.0.1:${HPORT}/"
      break
    fi
  fi
  sleep 1
  i=$((i + 1))
done

if [ -z "$URL" ]; then
  say "no webapp URL from hermes output after ${MAX}s readiness poll"
  if [ -f "$LOG" ]; then
    say "hermes log tail (redacted; full temp log will be deleted):"
    redact_log_tail "$LOG"
  fi
  if ! kill -0 "$HPID" 2>/dev/null; then
    die "hermes exited before advertising a URL"
  fi
  say "hermes still running (pid $HPID) but no URL yet; open whatever link hermes prints"
else
  say "webapp URL: $URL"
  if [ "$NO_OPEN" = 1 ]; then
    say "--no-open: not launching a browser"
  elif command -v termux-open-url >/dev/null 2>&1; then
    termux-open-url "$URL" || say "warning: termux-open-url failed for $URL"
  else
    say "termux-open-url not found; open $URL in a browser (install Termux:API matching your Termux build)"
  fi
fi
say "done. familia-start serves the GGUF; Hermes webapp is the phone UI."
say "  Hermes Desktop + Office 3D: on a Linux/macOS host,"
say "  hermes plugins install office-3d && hermes plugins enable office-3d"
if kill -0 "$HPID" 2>/dev/null; then
  say "hermes webapp pid $HPID; familia-start pid ${FSPID:-unknown}"
else
  say "hermes exited early; familia-start pid ${FSPID:-unknown}"
fi
