#!/bin/sh
# C2C stage 1 loopback: two llama-servers, same tiny model, same build, same ctx/kv.
# Prompt A, save slot 0, ship (local copy), restore into B, and check B
# reuses the cache (n_restored == n_saved; B's next completion hits cache).
# Usage: loopback_test.sh LLAMA_SERVER GGUF [WORKDIR]
set -eu
BIN=$1; GGUF=$2; W=${3:-$(mktemp -d)}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$W/a" "$W/b"
PA=${PA:-18571}; PB=${PB:-18572}
common="-m $GGUF -c 512 -np 1 -t 2 -ctk f16 -ctv f16 --host 127.0.0.1"
"$BIN" $common --port $PA --slot-save-path "$W/a" >"$W/a.log" 2>&1 & A=$!
"$BIN" $common --port $PB --slot-save-path "$W/b" >"$W/b.log" 2>&1 & B=$!
trap 'kill $A $B 2>/dev/null' EXIT
for p in $PA $PB; do i=0; until curl -sf http://127.0.0.1:$p/health >/dev/null; do i=$((i+1)); [ $i -gt 60 ] && { echo "server $p failed"; cat "$W"/*.log; exit 1; }; sleep 1; done; done
P='Once upon a time, there was a little girl named Lily. She loved to play outside'
curl -sf http://127.0.0.1:$PA/completion -d "{\"prompt\":\"$P\",\"n_predict\":16,\"temperature\":0,\"cache_prompt\":true,\"id_slot\":0}" >"$W/a.json"
python3 "$HERE/kv_ship.py" ship --src http://127.0.0.1:$PA --dst http://127.0.0.1:$PB \
  --src-model "$GGUF" --dst-model "$GGUF" --src-dir "$W/a" --dst-dir "$W/b" --via local
curl -sf http://127.0.0.1:$PB/completion -d "{\"prompt\":\"$P\",\"n_predict\":16,\"temperature\":0,\"cache_prompt\":true,\"id_slot\":0}" >"$W/b.json"
python3 - "$W/a.json" "$W/b.json" <<'PY'
import json,sys
a,b=(json.load(open(f)) for f in sys.argv[1:])
ta,tb=a["timings"],b["timings"]
print(f"A prompt_n={ta['prompt_n']}  B prompt_n={tb['prompt_n']} (cache_n={tb.get('cache_n')})")
assert a["content"]==b["content"], (a["content"],b["content"])
assert tb["prompt_n"] < ta["prompt_n"], "B did not reuse shipped KV"
print("LOOPBACK OK: identical output, B reused shipped KV")
PY
