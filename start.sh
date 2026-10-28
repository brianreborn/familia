#!/bin/sh
# FAMILIA: Super-project launcher
# Pure POSIX /bin/sh.
set -eu
case "${1:-}" in -h|--help) cat <<'USAGE'
start.sh: Start the active local topology declared in graph.yaml.
Usage:
  sh start.sh [--host NAME] [--dry-run] [--yes]
    --host NAME  select a declared graph host (default: exact local hostname match)
    --dry-run    print the local graph plan; start nothing
    --yes        accept the license review without a prompt (summary still printed)
  sh start.sh --bootstrap [backend args...]
    Explicitly start the legacy standalone code-bootstraps-llama.cpp UI/router.
    DETACH_MODE=screen-attached|screen|tmux|nohup|foreground picks how it runs.
    Default is screen-attached: named session familia-server, 10000 scrollback, reattach with screen -r.
Example: DETACH_MODE=foreground sh start.sh --host miryam
USAGE
  exit 0 ;; esac

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
say() { printf '%s\n' "familia: $*" >&2; }
# absolute form of a path, for "logs:" lines only (the path itself is unchanged)
abs_path() { case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s\n' "$PWD/$1" ;; esac; }

if [ "${1:-}" != "--bootstrap" ]; then
  GRAPH_START="$ROOT/scripts/start_graph.py"
  case "${PREFIX:-}" in
    *com.termux*) command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock >/dev/null 2>&1 && say "wake-lock acquired" || true ;;
  esac
  case "${1:-}" in
    --dry-run|-n) exec python3 "$GRAPH_START" "$@" ;;
  esac
  # Single-node default: a host that is not in graph.yaml (or has no active local
  # nodes) runs the pinned code-bootstraps click-and-go with the default model
  # (LFM3-1.7B-Uncensored) on 127.0.0.1:${PORT:-9931}. FAMILIA_SINGLE_NODE=0 disables.
  if [ "${FAMILIA_SINGLE_NODE:-1}" != 0 ] && [ -f "$ROOT/code-bootstraps-llama.cpp/start.sh" ]; then
    _rc=0; _probe=$(python3 "$GRAPH_START" --dry-run "$@" 2>&1) || _rc=$?
    case "$_rc:$_probe" in
      3:*|*"is not declared in graph.yaml"*|*"nothing would start"*|*"graph validation failed"*)
        say "this host has no familia topology yet; starting the single-node default (LFM3-1.7B-Uncensored via code-bootstraps-llama.cpp)"
        say "to join the fleet later: python3 scripts/host_measure.py --name NAME ... (see QUICKSTART.md)"
        exec sh "$ROOT/code-bootstraps-llama.cpp/start.sh" ;;
    esac
  fi
  DETACH_MODE="${DETACH_MODE:-screen-attached}"
  LOG_FILE="${LOG_FILE:-$ROOT/.cache/graph.log}"
  mkdir -p "$(dirname "$LOG_FILE")"
  say "logs: $(abs_path "$LOG_FILE")"
  _run_graph_detached() {
    nohup python3 "$GRAPH_START" "$@" >> "$LOG_FILE" 2>&1 &
    disown $! 2>/dev/null || true
    say "graph supervisor PID: $! (log $LOG_FILE)"
  }
  case "$DETACH_MODE" in
    tmux)
      if command -v tmux >/dev/null 2>&1; then
        say "launching graph topology in tmux session familia-server (log $LOG_FILE)"
        exec tmux new-session -d -s familia-server "python3 '$GRAPH_START' $*"
      fi
      say "tmux requested but not found; falling back to nohup"
      _run_graph_detached "$@"
      ;;
    screen)
      if command -v screen >/dev/null 2>&1; then
        say "launching graph topology in screen session familia-server (10000 lines of scrollback; log $LOG_FILE)"
        exec screen -h 10000 -dmS familia-server python3 "$GRAPH_START" "$@"
      fi
      say "screen requested but not found; falling back to nohup"
      _run_graph_detached "$@"
      ;;
    screen-attached)
      if command -v screen >/dev/null 2>&1; then
        say "launching attached graph topology in screen session familia-server (10000 lines of scrollback; detach with Ctrl-A then D; reattach with screen -r familia-server)"
        exec screen -h 10000 -S familia-server python3 "$GRAPH_START" "$@"
      fi
      say "screen-attached default but screen is not installed; falling back to foreground (install screen for reattachable sessions)"
      exec python3 "$GRAPH_START" "$@"
      ;;
    nohup)
      say "launching graph topology detached with nohup (logging to $LOG_FILE)"
      _run_graph_detached "$@"
      ;;
    foreground|"")
      exec python3 "$GRAPH_START" "$@"
      ;;
    *)
      say "unknown DETACH_MODE=$DETACH_MODE (foreground|nohup|tmux|screen|screen-attached)"
      exit 1
      ;;
  esac
  exit 0
fi
shift

DRY=0
case "${1:-}" in
  --dry-run|-n) DRY=1; shift ;;
  --yes|-y) export FAMILIA_ACCEPT_LICENSES=yes; shift ;;
esac

# Detect Termux (Android)
TERMUX=0
case "${PREFIX:-}" in *com.termux*) TERMUX=1 ;; esac

# On Android/Termux, enforce wake-lock so the server survives backgrounding (#7).
if [ "$TERMUX" = 1 ] && command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock >/dev/null 2>&1 && say "wake-lock acquired" || true
fi

# Licenses first: show what this selection brings in before anything runs (docs/licenses.md).
if [ "$DRY" = 1 ]; then
  say "[dry-run] would check licenses (python3 scripts/licenses.py gate), then sync the pinned parts (scripts/sync_pins.py) and run the backend start.sh $*"
  python3 "$ROOT/scripts/sync_pins.py" --dry-run || true
  say "[dry-run] DETACH_MODE=${DETACH_MODE:-screen-attached}, log ${LOG_FILE:-$ROOT/.cache/server.log}"
  exit 0
fi
if command -v python3 >/dev/null 2>&1; then
  python3 "$ROOT/scripts/licenses.py" gate || {
    rc=$?; say "licenses not accepted; nothing started. Review them: python3 scripts/licenses.py review"; exit $rc; }
else
  say "python3 not found, so the license review can't run. Install Python 3 (Termux: pkg install python), then retry."
  exit 1
fi

# Pinned parts first, all together (REQUIREMENTS.md R-sync; scripts/sync_pins.py).
if [ -f "$ROOT/scripts/sync_pins.py" ]; then
  python3 "$ROOT/scripts/sync_pins.py" --auto || { rc=$?; echo "start.sh: the pinned parts could not be synced (see above); stopped" >&2; exit $rc; }
  FAMILIA_SYNC_DONE="$ROOT"; export FAMILIA_SYNC_DONE
fi

BACKEND_START="$ROOT/code-bootstraps-llama.cpp/start.sh"
if [ ! -f "$BACKEND_START" ] && [ -f "$ROOT/../code-bootstraps-llama.cpp/start.sh" ]; then
  BACKEND_START="$ROOT/../code-bootstraps-llama.cpp/start.sh"
fi

if [ ! -f "$BACKEND_START" ]; then
  say "the model server launcher (code-bootstraps-llama.cpp/start.sh) is missing."
  say "Next: run sh scripts/configure.sh to fetch it, then sh start.sh again."
  exit 1
fi


# One instance per port (docs/api-key-design.md): probe it WITH the instance key first.
#   up (0)            -> already running: reuse it, do not bootstrap a second one
#   key rejected (4)  -> a server is there but rejects our key: misconfiguration, stop loudly
#   nothing there (3) -> start it
if [ "${FAMILIA_FORCE_BOOTSTRAP:-0}" != 1 ]; then
  probe_rc=0
  python3 "$ROOT/scripts/familia_auth.py" probe "http://127.0.0.1:${PORT:-9931}" || probe_rc=$?
  case "$probe_rc" in
    0) say "a server already answers on :${PORT:-9931} with this instance's key; reusing it (FAMILIA_FORCE_BOOTSTRAP=1 to start anyway)"; exit 0 ;;
    4) say "ERROR: :${PORT:-9931} is running but rejects this instance's API key. Not starting another server. Check ${XDG_CONFIG_HOME:-$HOME/.config}/familia/instances/${PORT:-9931}/api-keys"; exit 4 ;;
  esac
fi

# DETACH_MODE support. screen-attached is the default (attached + reattachable via
# screen -r familia-server). Override with DETACH_MODE=foreground|nohup|tmux|screen.
DETACH_MODE="${DETACH_MODE:-screen-attached}"

# One detach, one log (code-bootstraps-llama.cpp #18 / familia start):
# when we detach here, the backend must run in the foreground and share LOG_FILE.
export LOG_FILE="${LOG_FILE:-$ROOT/.cache/server.log}"
mkdir -p "$(dirname "$LOG_FILE")"
[ "${FAMILIA_DETACHED:-}" = 1 ] || say "logs: $(abs_path "$LOG_FILE")"

_run_backend_detached() {
  # Already detached in this process tree; backend stays foreground.
  export FAMILIA_DETACHED=1
  export DETACH_MODE=foreground
  export LOG_FILE
  nohup sh "$BACKEND_START" "$@" >> "$LOG_FILE" 2>&1 &
  disown $! 2>/dev/null || true
  say "server PID: $! (log $LOG_FILE)"
}

case "$DETACH_MODE" in
  tmux)
    if command -v tmux >/dev/null 2>&1; then
      say "launching detached inside tmux session familia-server (log $LOG_FILE)"
      exec tmux new-session -d -s familia-server         "env FAMILIA_DETACHED=1 DETACH_MODE=foreground LOG_FILE='$LOG_FILE' sh '$BACKEND_START' $*"
    else
      say "tmux requested but not found; falling back to nohup"
      _run_backend_detached "$@"
    fi
    ;;
  screen)
    if command -v screen >/dev/null 2>&1; then
      say "launching detached inside screen session familia-server (10000 lines of scrollback; log $LOG_FILE)"
      exec screen -h 10000 -dmS familia-server env FAMILIA_DETACHED=1 DETACH_MODE=foreground LOG_FILE="$LOG_FILE" sh "$BACKEND_START" "$@"
    else
      say "screen requested but not found; falling back to nohup"
      _run_backend_detached "$@"
    fi
    ;;
  screen-attached)
    if command -v screen >/dev/null 2>&1; then
      say "launching attached inside screen session familia-server (10000 lines of scrollback; detach with Ctrl-A then D; reattach with screen -r familia-server)"
      exec screen -h 10000 -S familia-server env FAMILIA_DETACHED=1 DETACH_MODE=foreground LOG_FILE="$LOG_FILE" sh "$BACKEND_START" "$@"
    else
      say "screen-attached default but screen is not installed; falling back to foreground (install screen for reattachable sessions)"
      exec sh "$BACKEND_START" "$@"
    fi
    ;;
  nohup)
    say "launching detached with nohup (logging to $LOG_FILE)"
    _run_backend_detached "$@"
    ;;
  foreground|"")
    exec sh "$BACKEND_START" "$@"
    ;;
  *)
    say "unknown DETACH_MODE=$DETACH_MODE (foreground|nohup|tmux|screen|screen-attached)"
    exit 1
    ;;
esac
