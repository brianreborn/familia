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
MK_TAG=familia; . "$ROOT/lib/msg.mk"   # say
. "$ROOT/lib/path.mk"   # abs_path: absolute form of a path, for "logs:" lines only
. "$ROOT/lib/os.mk"     # mk_is_termux

# The home menu reads FAMILIA_PIDFILE after this script returns. Record the
# process that holds the LISTEN socket, not a wrapper that has already exited.
_write_listener_pid() {
  [ -n "${FAMILIA_PIDFILE:-}" ] || return 0
  _lport=${PORT:-9931}
  _lpid=$(PORT="$_lport" python3 -c '
import os
port = int(os.environ.get("PORT") or "9931")
want = "%04X" % port
inodes = set()
for name in ("tcp", "tcp6"):
    path = "/proc/net/" + name
    try:
        lines = open(path, encoding="ascii", errors="replace")
    except OSError:
        continue
    for line in lines:
        fields = line.split()
        if len(fields) < 10 or fields[0] == "sl":
            continue
        if not fields[1].endswith(":" + want) or fields[3] != "0A":
            continue
        inodes.add(fields[9])
if not inodes:
    raise SystemExit(0)
for name in os.listdir("/proc"):
    if not name.isdigit():
        continue
    fd_dir = "/proc/" + name + "/fd"
    try:
        fds = os.listdir(fd_dir)
    except OSError:
        continue
    for fd in fds:
        try:
            target = os.readlink(os.path.join(fd_dir, fd))
        except OSError:
            continue
        if target.startswith("socket:[") and target[8:-1] in inodes:
            print(name)
            raise SystemExit(0)
' ) || _lpid=
  if [ -z "${_lpid:-}" ] && command -v sockstat >/dev/null 2>&1; then
    _lpid=$(sockstat -l -P tcp -p "$_lport" 2>/dev/null | awk 'NR>1 { print $3; exit }') || _lpid=
  fi
  if [ -z "${_lpid:-}" ]; then
    say "server on :${_lport} is up but its pid could not be recorded"
    return 0
  fi
  _stage=${FAMILIA_PIDFILE}.tmp.$$
  printf '%s\n' "$_lpid" > "$_stage" && mv -f "$_stage" "$FAMILIA_PIDFILE"
  say "recorded server pid $_lpid"
}

# Single-node hosts fall into the --bootstrap section below. Do not call this
# script again: that would be a second copy, and the menu must keep calling
# `sh start.sh` so a host with a graph still takes the graph path.
_enter_bootstrap=0
if [ "${1:-}" != "--bootstrap" ]; then
  GRAPH_START="$ROOT/scripts/start_graph.py"
  if mk_is_termux; then
    command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock >/dev/null 2>&1 && say "wake-lock acquired" || true
  fi
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
        _enter_bootstrap=1
        ;;
    esac
  fi
  if [ "$_enter_bootstrap" = 0 ]; then
  DETACH_MODE="${DETACH_MODE:-screen-attached}"
  LOG_FILE="${LOG_FILE:-$ROOT/.cache/graph.log}"
  mkdir -p "$(dirname "$LOG_FILE")"
  say "logs: $(abs_path "$LOG_FILE")"
  _write_pid() {
    # Optional. The home menu reads this after a license prompt, instead of scraping logs.
    [ -n "${FAMILIA_PIDFILE:-}" ] || return 0
    _stage=${FAMILIA_PIDFILE}.tmp.$$
    printf '%s\n' "$1" > "$_stage" && mv -f "$_stage" "$FAMILIA_PIDFILE"
  }
  _run_graph_detached() {
    nohup python3 "$GRAPH_START" "$@" >> "$LOG_FILE" 2>&1 &
    disown $! 2>/dev/null || true
    say "graph supervisor PID: $! (log $LOG_FILE)"
    _write_pid "$!"
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
fi
if [ "$_enter_bootstrap" = 0 ]; then
  shift
fi

DRY=0
case "${1:-}" in
  --dry-run|-n) DRY=1; shift ;;
  --yes|-y) export FAMILIA_ACCEPT_LICENSES=yes; shift ;;
esac

# Detect Termux (Android)
TERMUX=0
if mk_is_termux; then TERMUX=1; fi

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

# One instance per port (docs/api-key-design.md): probe it WITH the instance key first.
#   up (0)            -> already running: reuse it, do not bootstrap a second one
#   key rejected (4)  -> a server is there but rejects our key: misconfiguration, stop loudly
#   nothing there (3) -> start it
# Reuse does not need the backend checkout. Record the listener so stop can signal it.
if [ "${FAMILIA_FORCE_BOOTSTRAP:-0}" != 1 ]; then
  probe_rc=0
  python3 "$ROOT/scripts/familia_auth.py" probe "http://127.0.0.1:${PORT:-9931}" || probe_rc=$?
  case "$probe_rc" in
    0) say "a server already answers on :${PORT:-9931} with this instance's key; reusing it (FAMILIA_FORCE_BOOTSTRAP=1 to start anyway)"; _write_listener_pid; exit 0 ;;
    4) say "ERROR: :${PORT:-9931} is running but rejects this instance's API key. Not starting another server. Check ${XDG_CONFIG_HOME:-$HOME/.config}/familia/instances/${PORT:-9931}/api-keys"; exit 4 ;;
  esac
fi

if [ ! -f "$BACKEND_START" ]; then
  say "the model server launcher (code-bootstraps-llama.cpp/start.sh) is missing."
  say "Next: run sh scripts/configure.sh to fetch it, then sh start.sh again."
  exit 1
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
  if [ -n "${FAMILIA_PIDFILE:-}" ]; then
    _stage=${FAMILIA_PIDFILE}.tmp.$$
    printf '%s\n' "$!" > "$_stage" && mv -f "$_stage" "$FAMILIA_PIDFILE"
  fi
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
