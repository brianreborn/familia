#!/usr/bin/env bash
# android_multi_start.sh – set up SSH key auth (once) and launch Android pentest nodes
# Usage: export ANDROID_A_PASS="..." ANDROID_B_PASS="..."; bash ./android_multi_start.sh

set -euo pipefail

# ---- Ensure a local SSH key exists ----
if [[ ! -f "$HOME/.ssh/id_rsa" ]]; then
  echo "Generating new SSH keypair..."
  ssh-keygen -t rsa -b 4096 -N "" -f "$HOME/.ssh/id_rsa"
fi
PUB_KEY="$(cat "$HOME/.ssh/id_rsa.pub")"

# ---- Device list (IP USER PASS) ----
# Add/remove entries as needed.
DEVICES=(
  "192.168.1.7 u0_a439 ${ANDROID_A_PASS:-}"
  "192.168.1.8 u0_a414 ${ANDROID_B_PASS:-}"
)

# ---- Helper: copy public key using password once (fallback to username) ----
copy_key() {
  local ip="$1" user="$2" pass="${3:-$user}"
  if [[ -z "$pass" ]]; then
    echo "[INFO] No password supplied; using username ($user) as password for $user@$ip."
  fi
  echo "Copying SSH public key to $user@$ip..."
  sshpass -p "$pass" ssh -o StrictHostKeyChecking=no -p 8022 "$user@$ip" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo \"$PUB_KEY\" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
}

# ---- Helper: start Android node via key auth ----
start_node() {
  local ip="$1" user="$2"
  echo "Starting Android node on $user@$ip..."
  ssh -o StrictHostKeyChecking=no -p 8022 "$user@$ip" "cd /data/local/tmp && ./start-green-roomz.sh && echo 'Node started'"
}

# ---- Main loop ----
for desc in "${DEVICES[@]}"; do
  read -r IP USER PASS <<<"$desc"
  echo "=== Processing $USER@$IP ==="
  # Ensure key is present (password only needed the first time)
  copy_key "$IP" "$USER" "$PASS"
  # Start the node (key auth)
  start_node "$IP" "$USER"
  # Register with fleet (key auth)
  echo "Registering $USER node with fleet..."
  ./with-fleet.sh --role pentest --manifest scripts/pentest-role.json
  echo "Done for $USER@$IP."
  echo
 done

echo "All devices processed."
