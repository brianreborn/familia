#!/usr/bin/env bash
# Script to start the Android node for the swarm.
# Env: ANDROID_HOST, ANDROID_USER, optional ANDROID_PORT (8022), ANDROID_SSH_PASSWORD.

# Device settings come from the environment; nothing is hardcoded.
: "${ANDROID_HOST:?set ANDROID_HOST to the Android device address}"
: "${ANDROID_USER:?set ANDROID_USER to the Termux user (e.g. u0_a123)}"
ANDROID_PORT=${ANDROID_PORT:-8022}
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -p "$ANDROID_PORT")
SSH=(ssh)

# Prefer key-based auth. Password auth only when ANDROID_SSH_PASSWORD is set,
# passed via SSHPASS (sshpass -e) so it never appears in the process list.
if [ -n "${ANDROID_SSH_PASSWORD:-}" ]; then
  if ! command -v sshpass >/dev/null 2>&1; then
    echo "android_start.sh: ANDROID_SSH_PASSWORD is set but sshpass is not installed; install it or use an SSH key" >&2
    exit 1
  fi
  export SSHPASS="$ANDROID_SSH_PASSWORD"
  SSH=(sshpass -e ssh)
fi

# Launch the remote start script on the Android device
"${SSH[@]}" "${SSH_OPTS[@]}" "$ANDROID_USER@$ANDROID_HOST" "\
  cd /data/local/tmp && \
  if [ ! -x ./start-green-roomz.sh ]; then echo 'start-green-roomz.sh not deployed to /data/local/tmp' >&2; exit 1; fi && \
  ./start-green-roomz.sh && \
  echo 'Android node started'"

# Register the node with the fleet. with-fleet.sh and scripts/pentest-role.json
# are not shipped in this repo (see #15); fail loudly instead of erroring later.
for f in ./with-fleet.sh scripts/pentest-role.json; do
  if [ ! -e "$f" ]; then
    echo "android_start.sh: missing $f; fleet registration skipped (see issue #15)" >&2
    exit 1
  fi
done
./with-fleet.sh --role pentest --manifest scripts/pentest-role.json

echo "Android pentest node launched and registered."
