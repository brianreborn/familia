#!/usr/bin/env bash
# Script to start the Android node for the swarm.
# Requires sshpass installed and the SSH password for the Android device.

# Ensure sshpass is available
if ! command -v sshpass >/dev/null 2>&1; then
  echo "sshpass not found, installing..."
  sudo apt-get update && sudo apt-get install -y sshpass
fi

# Retrieve password from environment variable or prompt
if [ -z "$ANDROID_SSH_PASSWORD" ]; then
  read -s -p "Enter SSH password for Android (u0_a439@192.168.1.6): " ANDROID_SSH_PASSWORD
  echo
fi

# Launch the remote start script on the Android device
sshpass -p "$ANDROID_SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p 8022 u0_a439@192.168.1.6 "\
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
