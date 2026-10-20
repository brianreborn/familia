#!/usr/bin/env bash
# #90: measure layer-at-a-time streaming (GPU layer_stream and CPU disk-stream) and compare
# with plan_placement.py predictions. Usage: validate_layer_stream.sh LINKS.jsonl MODEL.gguf... 
# Env: HOST (record name). Prints one JSON line per measurement; appends disk_read to LINKS.
set -u; R=$(cd "$(dirname "$0")/../.." && pwd); L=$1; shift
mkdir -p "$R/.cache"; X="$R/.cache/layer_stream"
[ "$X" -nt "$R/gpu-legacy/layer_stream.c" ] || cc -O2 -o "$X" "$R/gpu-legacy/layer_stream.c" -ldl
B=${RAM_BUDGET_MIB:-1024}; T=${THREADS:-4}
if ! grep -q '"disk_read"' "$L"; then
  f=$1
  # dd prints "N bytes ... copied, S s, ..."; recompute from bytes/sec for a stable unit
  read -r by sec < <(dd if="$f" of=/dev/null bs=4M count=256 skip=256 iflag=direct 2>&1 | awk '/copied/{print $1, $(NF-3)}')
  echo "{\"link\":\"disk_read\",\"how\":\"dd O_DIRECT 4M\",\"bytes\":$by,\"GBps\":$(python3 -c "print(round($by/$sec/1e9,3))"),\"host\":\"${HOST:-$(hostname -s)}\",\"time\":\"$(date +%FT%T%z)\"}" >> "$L"
fi
for m in "$@"; do
  read -r lm nl < <(python3 "$R/scripts/plan_placement.py" "$L" "$m" --placement layer-stream | python3 -c "import sys,json;d=json.loads(sys.stdin.readline());print(d['unit_MiB'],d['units'])")
  g=$("$X" "$lm" "$nl" 3 2>&1 | tail -1); tg=$(echo "$g" | python3 -c "import sys,json;print(json.load(sys.stdin)['tok_s'])" 2>/dev/null)
  [ -n "$tg" ] && python3 "$R/scripts/plan_placement.py" "$L" "$m" --placement layer-stream --measured "$tg" | sed "s|^{|{\"model\":\"$(basename "$m")\",\"measured_by\":\"layer_stream $lm MiB x $nl\",|"
  [ -z "$tg" ] && echo "{\"model\":\"$(basename "$m")\",\"layer_stream\":\"failed: $g\"}"
  # disk-stream is predicted only: measuring it needs a cgroup cap below the model size, which
  # the headroom-cap policy (4ae6e13) forbids. One pre-policy point is in docs/design (2B, +15.6%).
done
