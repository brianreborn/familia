#!/bin/bash
# harness_driver.sh MODEL [THREADS]: plain llama.cpp vs hermes single / --graph vs Harness² on one llama-server.
# Rows: harness, prompt tokens sent, TTFT, tg. hermes rows use the prompt hermes would send (--render-only),
# replayed to the same server, so tools are never executed. Output: ~/perf/harness.md
SCR=$(umask 077; mktemp -d "${TMPDIR:-/tmp}/harness.XXXXXX") || exit 1; trap 'rm -rf "$SCR"' EXIT
M=$1; T=${2:-4}; F=~/repositories/familia; B=$F/code-bootstraps-llama.cpp/build-linux-x86_64/bin; O=~/perf/harness.md; P=18099
python3 $F/scripts/bench_guard.py meta $M --default "sampling=temp 0 (harness timing)" > /dev/null || { echo "GUARD-FAIL $M" >> $O; exit 3; }
systemd-run --user --scope -q -p MemoryHigh=$(( $(awk "/MemAvailable/{print int(\$2/1024)}" /proc/meminfo) - 1536 ))M $B/llama-server -m $M -t $T -c 32768 --port $P -lm none --jinja > ~/perf/harness-server.log 2>&1 &
for i in $(seq 120); do curl -sf localhost:$P/health >/dev/null && break; sleep 2; done
q(){ python3 - "$1" "$2" <<'PY'
import json,sys,time,urllib.request
name,sysf=sys.argv[1],sys.argv[2]
s=open(sysf).read() if sysf!='-' else 'You are a helpful assistant.'
body=json.dumps({"messages":[{"role":"system","content":s},{"role":"user","content":"Write a Python function that reverses a string."}],"max_tokens":64,"temperature":0,"stream":True}).encode()
t=time.time();ft=None;n=0
for l in urllib.request.urlopen(urllib.request.Request("http://localhost:18099/v1/chat/completions",body,{"Content-Type":"application/json"}),timeout=3600):
  if l.startswith(b"data: {"):
    d=json.loads(l[6:]);
    if d.get("timings"): tm=d["timings"]
    if ft is None: ft=time.time()-t
    n+=1
tok=json.loads(urllib.request.urlopen(urllib.request.Request("http://localhost:18099/tokenize",json.dumps({"content":s}).encode())).read())["tokens"]
print("| %s | %d | %.2f s | %.2f | %s |"%(name,len(tok),ft or 0,tm.get("predicted_per_second",0) if 'tm' in dir() else 0,sysf.split('/')[-1]))
PY
}
echo "### $(basename $M) t$T $(date +%H:%M)" >> $O; echo "| harness | sys tokens | TTFT | tg t/s | prompt |" >> $O
q plain-llama.cpp - >> $O; q plain-llama.cpp-warm - >> $O
for mode in single graph; do d=$(mktemp -d); HERMES_HOME=$d sh $F/scripts/hermes.sh --mode $mode ${mode/single/--model coder} --render-only > $d/render.txt 2>&1
  f=$(ls $d/SOUL.md $d/*/SOUL.md 2>/dev/null | head -1); [ -n "$f" ] || f=$d/render.txt
  q hermes-$mode "$f" >> $O; q hermes-$mode-warm "$f" >> $O; done
/usr/bin/time -f "%e s wall %M KiB" python3 $F/scripts/harness2.py status > /dev/null 2> "$SCR/h2t"; echo "| harness2 status (mode off) | - | $(tail -1 "$SCR/h2t") | - | - |" >> $O
pkill -f "llama-server -m $M"
