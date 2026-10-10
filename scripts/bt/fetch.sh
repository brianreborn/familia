#!/usr/bin/env bash
# Fetch by REQ-REPO-02 key over the private tracker, verify, print path.
#   fetch.sh KEY TRACKER_URL DEST_DIR LISTEN_PORT [SHA256]
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
key=$1 tr=$2 dir=$3 port=$4 want=${5:-}
IFS=$'\t' read -r magnet path < <(python3 "$here/key.py" "$key" "$tr")
mkdir -p "$dir"
aria2c --seed-time=0 --enable-dht=false --enable-dht6=false --enable-peer-exchange=false --bt-enable-lpd=false \
  --bt-save-metadata=false --listen-port="$port" --dir="$dir" --console-log-level=warn --summary-interval=0 \
  --bt-stop-timeout=120 "$magnet"
f="$dir/$path"; [[ -f "$f" ]] || { echo "fetch: $f missing after download" >&2; exit 1; }
if [[ -n "$want" ]]; then
  got=$(sha256sum "$f" | cut -d' ' -f1)
  [[ "$got" == "$want" ]] || { echo "fetch: sha256 $got != $want" >&2; exit 1; }
fi
echo "$f"
