#!/usr/bin/env bash
# Tracker + seeder + leecher on 127.0.0.1; fetch by REQ-REPO-02 key; verify sha256.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd); bt=$here/scripts/bt
w=$(mktemp -d); trap 'kill $(jobs -p) 2>/dev/null; rm -rf "$w"' EXIT
mkdir -p "$w/seed" "$w/leech"
head -c $((24*1024*1024+123)) /dev/urandom > "$w/seed/slot0.bin"     # stand-in llama.cpp slot-save
want=$(sha256sum "$w/seed/slot0.bin" | cut -d' ' -f1)
tr=http://127.0.0.1:16969/announce
python3 "$bt/tracker.py" --bind 127.0.0.1 --port 16969 --allow-dir "$w/allow" > "$w/tracker.log" 2>&1 &
sleep 1
key=$(python3 "$bt/mktorrent.py" "$w/seed/slot0.bin" --announce "$tr" --out-dir "$w/t" --allow-dir "$w/allow")
echo "key: $key"
"$bt/seed.sh" "$w/t/"*.torrent "$w/seed" 16881 > "$w/seed.log" 2>&1 &
sleep 2
# unregistered infohash must be refused
python3 - <<PY
import urllib.request
r=urllib.request.urlopen("http://127.0.0.1:16969/announce?info_hash="+"%00"*20+"&port=1&left=0").read()
assert b"unregistered" in r, r; print("private: unregistered infohash refused")
PY
out=$(timeout 150 "$bt/fetch.sh" "$key" "$tr" "$w/leech" 16882 "$want")
echo "fetched: $out sha256=$want OK"
grep announce "$w/tracker.log"
