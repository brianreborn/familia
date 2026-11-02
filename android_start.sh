#!/usr/bin/env bash
# Start the Android node on one phone. Target comes from graph.yaml (#18):
#   ./android_start.sh phone7
# Env overrides: ANDROID_HOST, ANDROID_USER, ANDROID_PORT, ANDROID_DIR. Key-only SSH; no passwords.
# Runs as the Termux app user, which cannot exec from /data/local/tmp; default dir is Termux $HOME.
set -euo pipefail
case "${1:-}" in -h|--help) cat <<'USAGE'
android_start.sh: Start the familia node on one Android phone over key-only SSH (target from graph.yaml).
Usage:
  ./android_start.sh PHONE   (env overrides: ANDROID_HOST, ANDROID_USER, ANDROID_PORT)
Example: ./android_start.sh phone7
USAGE
  exit 0 ;; esac
cd "$(dirname "$0")"
read -r HOST USER PORT < <(python3 scripts/android_target.py "${1:-}")
DIR="${ANDROID_DIR:-\$HOME/green-roomz}"
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -p "$PORT" "$USER@$HOST")

"${SSH[@]}" "\
  cd \"$DIR\" && \
  if [ ! -x ./start-green-roomz.sh ]; then echo 'start-green-roomz.sh not deployed to $DIR' >&2; exit 1; fi && \
  ./start-green-roomz.sh && \
  echo 'Android node started'"

# with-fleet.sh and scripts/pentest-role.json are not shipped yet (#15); fail loudly.
for f in ./with-fleet.sh scripts/pentest-role.json; do
  [ -e "$f" ] || { echo "android_start.sh: missing $f; fleet registration skipped (see #15)" >&2; exit 1; }
done
./with-fleet.sh --role pentest --manifest scripts/pentest-role.json
echo "Android pentest node launched and registered."
