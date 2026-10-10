#!/usr/bin/env bash
# Watchdog: restart the Android node if it stops answering. Target from graph.yaml (#18):
#   ./watchdog_android.sh phone7      (env overrides: ANDROID_HOST/USER/PORT, WATCHDOG_INTERVAL)
set -uo pipefail
cd "$(dirname "$0")"
NAME=${1:-}
INTERVAL=${WATCHDOG_INTERVAL:-60}
LOG_FILE="$PWD/watchdog_android.log"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG_FILE" >&2; }
read -r HOST USER PORT < <(python3 scripts/android_target.py "$NAME") || exit 1
while true; do
  if ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -p "$PORT" "$USER@$HOST" "echo alive" >/dev/null 2>&1; then
    :
  else
    log "$USER@$HOST:$PORT unreachable; restarting"
    ./android_start.sh "$NAME" || log "restart failed"
  fi
  sleep "$INTERVAL"
done
