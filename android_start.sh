#!/usr/bin/env bash
# Start the Android node on one phone. Target comes from graph.yaml (#18):
#   ./android_start.sh phone7
# Env overrides: ANDROID_HOST, ANDROID_USER, ANDROID_PORT. Key-only SSH; no passwords.
set -euo pipefail
cd "$(dirname "$0")"
read -r HOST USER PORT < <(python3 scripts/android_target.py "${1:-}")
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -p "$PORT" "$USER@$HOST")

"${SSH[@]}" "\
  cd /data/local/tmp && \
  if [ ! -x ./start-green-roomz.sh ]; then echo 'start-green-roomz.sh not deployed to /data/local/tmp' >&2; exit 1; fi && \
  ./start-green-roomz.sh && \
  echo 'Android node started'"

# with-fleet.sh and scripts/pentest-role.json are not shipped yet (#15); fail loudly.
for f in ./with-fleet.sh scripts/pentest-role.json; do
  [ -e "$f" ] || { echo "android_start.sh: missing $f; fleet registration skipped (see #15)" >&2; exit 1; }
done
./with-fleet.sh --role pentest --manifest scripts/pentest-role.json
echo "Android pentest node launched and registered."
