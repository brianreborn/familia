#!/bin/sh
# FAMILIA: Super-project launcher
# Pure POSIX /bin/sh.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

say() { printf '%s\n' "familia: $*" >&2; }

# Detect Termux (Android)
TERMUX=0
case "${PREFIX:-}" in *com.termux*) TERMUX=1 ;; esac

# On Android/Termux, enforce wake-lock so the server survives backgrounding (#7).
if [ "$TERMUX" = 1 ] && command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock >/dev/null 2>&1 && say "wake-lock acquired" || true
fi

# Ensure configuration / subprojects exist
if [ ! -d "$ROOT/code-bootstraps-llama.cpp" ] && [ ! -d "$ROOT/../code-bootstraps-llama.cpp" ]; then
  sh "$ROOT/scripts/configure.sh"
fi

BACKEND_START="$ROOT/code-bootstraps-llama.cpp/start.sh"
if [ ! -f "$BACKEND_START" ] && [ -f "$ROOT/../code-bootstraps-llama.cpp/start.sh" ]; then
  BACKEND_START="$ROOT/../code-bootstraps-llama.cpp/start.sh"
fi

if [ ! -f "$BACKEND_START" ]; then
  say "start.sh backend not found. Run sh scripts/configure.sh first."
  exit 1
fi

# DETACH_MODE support: tmux > screen > nohup > foreground (default).
# On Termux, auto-detect the best available detach method unless overridden.
DETACH_MODE="${DETACH_MODE:-foreground}"
if [ "$TERMUX" = 1 ] && [ "$DETACH_MODE" = "foreground" ]; then
  # Default to nohup on Android so the server survives terminal close (#7).
  if command -v tmux >/dev/null 2>&1; then
    DETACH_MODE=tmux
  elif command -v screen >/dev/null 2>&1; then
    DETACH_MODE=screen
  else
    DETACH_MODE=nohup
  fi
  say "Termux detected, auto-selected DETACH_MODE=$DETACH_MODE"
fi

export DETACH_MODE

case "$DETACH_MODE" in
  tmux)
    if command -v tmux >/dev/null 2>&1; then
      say "launching detached inside tmux session familia-server"
      exec tmux new-session -d -s familia-server "sh '$BACKEND_START' $*"
    else
      say "tmux requested but not found; falling back to nohup"
      mkdir -p "$ROOT/.cache"
      nohup sh "$BACKEND_START" "$@" >> "$ROOT/.cache/server.log" 2>&1 &
      disown $! 2>/dev/null || true
      say "server PID: $!"
    fi
    ;;
  screen)
    if command -v screen >/dev/null 2>&1; then
      say "launching detached inside screen session familia-server"
      exec screen -dmS familia-server sh "$BACKEND_START" "$@"
    else
      say "screen requested but not found; falling back to nohup"
      mkdir -p "$ROOT/.cache"
      nohup sh "$BACKEND_START" "$@" >> "$ROOT/.cache/server.log" 2>&1 &
      disown $! 2>/dev/null || true
      say "server PID: $!"
    fi
    ;;
  nohup)
    say "launching detached with nohup (logging to .cache/server.log)"
    mkdir -p "$ROOT/.cache"
    nohup sh "$BACKEND_START" "$@" >> "$ROOT/.cache/server.log" 2>&1 &
    disown $! 2>/dev/null || true
    say "server PID: $!"
    ;;
  foreground|"")
    exec sh "$BACKEND_START" "$@"
    ;;
  *)
    say "unknown DETACH_MODE=$DETACH_MODE (foreground|nohup|tmux|screen)"
    exit 1
    ;;
esac
