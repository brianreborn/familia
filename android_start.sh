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
  ./start-green-roomz.sh && \
  echo 'Android node started'\"

# Register the node with the fleet using the existing with-fleet.sh helper
# Assuming with-fleet.sh is in the repo root
./with-fleet.sh --role pentest --manifest scripts/pentest-role.json

echo "Android pentest node launched and registered."
