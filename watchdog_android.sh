#!/usr/bin/env bash
# watchdog_android.sh – monitor Android pentest node health and restart if needed

# Configuration
ANDROID_USER="u0_a439"
ANDROID_HOST="192.168.1.6"
ANDROID_PORT=8022
# Password (optional; key auth preferred) comes from ANDROID_SSH_PASSWORD.
# ANDROID_PASSWORD is accepted as a deprecated alias.
if [ -z "${ANDROID_SSH_PASSWORD:-}" ] && [ -n "${ANDROID_PASSWORD:-}" ]; then
  echo "familia: ANDROID_PASSWORD is deprecated; use ANDROID_SSH_PASSWORD" >&2
  ANDROID_SSH_PASSWORD="$ANDROID_PASSWORD"
fi
PASSWORD_VAR="ANDROID_SSH_PASSWORD"
CHECK_INTERVAL=60  # seconds
LOG_FILE="$(dirname "$0")/watchdog_android.log"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

check_node() {
  if command -v sshpass >/dev/null; then
    sshpass -p "${!PASSWORD_VAR}" ssh -o ConnectTimeout=5 -p $ANDROID_PORT $ANDROID_USER@$ANDROID_HOST "echo alive" >/dev/null 2>&1
    return $?
  else
    ssh -o BatchMode=yes -o ConnectTimeout=5 -p $ANDROID_PORT $ANDROID_USER@$ANDROID_HOST "echo alive" >/dev/null 2>&1
    return $?
  fi
}

restart_node() {
  log "Attempting to start Android node via android_start.sh"
  bash "$(pwd)/android_start.sh"
}

while true; do
  if check_node; then
    log "Android node responsive"
  else
    log "Android node unresponsive"
    restart_node
  fi
  sleep $CHECK_INTERVAL
done
