#!/usr/bin/env bash
# Seed a file from its .torrent with aria2c. No DHT, no PEX, no LPD (private).
#   seed.sh TORRENT DATA_DIR LISTEN_PORT [EXTRA aria2c args]
set -euo pipefail
t=$1 dir=$2 port=$3; shift 3
exec aria2c --seed-ratio=0.0 --check-integrity=true --bt-seed-unverified=false \
  --enable-dht=false --enable-dht6=false --enable-peer-exchange=false --bt-enable-lpd=false \
  --listen-port="$port" --dir="$dir" --console-log-level=warn --summary-interval=0 "$@" "$t"
