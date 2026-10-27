#!/bin/sh
# prefetch-first-models.sh: free-download first-try CPU models (protomodel / safe-build).
# Soft-fail. Foreground mode does the work; --background detaches to .cache log.
# CPU/safe models only — no GGUF-on-8600. Called from the gum home / setup / proto paths.
# Usage:
#   sh scripts/prefetch-first-models.sh              # run fetches (blocking)
#   sh scripts/prefetch-first-models.sh --background # nohup into .cache/prefetch-first-models.log
#   sh scripts/prefetch-first-models.sh --dry-run
#   sh scripts/prefetch-first-models.sh --status
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}
CACHE=$ROOT/.cache
LOG=$CACHE/prefetch-first-models.log
PIDF=$CACHE/prefetch-first-models.pid
BG=0
DRY=0
STATUS=0

say() { printf 'prefetch: %s\n' "$*" >&2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --background|-b) BG=1 ;;
    --dry-run|-n) DRY=1 ;;
    --status) STATUS=1 ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) say "unknown arg $1"; exit 2 ;;
  esac
  shift
done

mkdir -p "$CACHE"

if [ "$STATUS" = 1 ]; then
  if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    say "RUNNING pid=$(cat "$PIDF") log=$LOG"
  elif [ -f "$LOG" ]; then
    say "IDLE last-log=$LOG"
    tail -n 3 "$LOG" 2>/dev/null | sed 's/^/  /' >&2 || true
  else
    say "IDLE (never started)"
  fi
  exit 0
fi

# Already running?
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; then
  say "already running pid=$(cat "$PIDF") — see $LOG"
  exit 0
fi

# First-try CPU models (protomodel chat face + safe-build decision/route).
# bartowski SmolLM2-135M Q4_0 (~100MB class); ggml-org Laya-Q8_0 (~429MB).
MODELS="
bartowski/SmolLM2-135M-Instruct-GGUF@09816acd5d99df7be770d85ea30822623dab342c|SmolLM2-135M-Instruct-Q4_0.gguf|chat
ggml-org/Laya-GGUF@da4b4753d62197659d8c90103cd4c43bef9afea6|Laya-Q8_0.gguf|decision
"

do_fetch() {
  echo "prefetch: start $(date -Iseconds 2>/dev/null || date)"
  if ! command -v "$PY" >/dev/null 2>&1; then
    echo "prefetch: no python; skip"
    return 0
  fi
  if [ ! -f "$ROOT/scripts/add_model.py" ]; then
    echo "prefetch: add_model.py missing; skip"
    return 0
  fi
  echo "$MODELS" | while IFS='|' read -r spec file role; do
    [ -n "${spec:-}" ] || continue
    echo "prefetch: ORDNANCE $spec ($file) role=$role"
    if [ "$DRY" = 1 ]; then
      echo "prefetch: [dry-run] $PY scripts/add_model.py --fetch $spec --file $file --role $role --yes"
      continue
    fi
    # Soft-fail each fetch; never abort the batch.
    FAMILIA_ACCEPT_LICENSES=yes "$PY" "$ROOT/scripts/add_model.py" \
      --fetch "$spec" --file "$file" --role "$role" --yes \
      || echo "prefetch: WARN fetch failed for $spec (non-fatal)"
  done
  echo "prefetch: done $(date -Iseconds 2>/dev/null || date)"
}

if [ "$DRY" = 1 ] && [ "$BG" != 1 ]; then
  do_fetch
  exit 0
fi

if [ "$BG" = 1 ]; then
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would nohup into $LOG"
    exit 0
  fi
  # Detach: foreground build/UI continues while models land.
  (
    echo $$ > "$PIDF"
    do_fetch
    rm -f "$PIDF"
  ) >>"$LOG" 2>&1 &
  echo $! > "$PIDF"
  say "background pid=$(cat "$PIDF") log=$LOG"
  exit 0
fi

do_fetch
