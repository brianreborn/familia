#!/usr/bin/env bash
# #93: PrismML Ternary-Bonsai-2 check, one model at a time: GGUF metadata guard, llama-bench,
# llama-server tool calling (plain OpenAI tools, hermes-rendered system prompt + tools) and a
# Harness² base evaluation (coding-v1, 3 tasks). Needs the PrismML llama.cpp fork (PQ2_0/PTQ1_0
# kernels; upstream runs only Q2_0). Usage: bonsai_check.sh MODEL.gguf...  Env: LLAMA_BIN (dir with
# llama-bench, llama-server). Memory: launched only via bench_capped.sh / bench_guard headroom cap, THREADS (4), PORT (18193). One JSON line per model on stdout.
set -u; R=$(cd "$(dirname "$0")/../.." && pwd); BIN=${LLAMA_BIN:?LLAMA_BIN}; T=${THREADS:-4}; P=${PORT:-18193}
# card (README "We recommend these sampling settings"), non-thinking mode, used for tool calls:
SAMP="--temp 0.7 --top-p 0.8 --top-k 20 --min-p 0 --presence-penalty 1.5 --repeat-penalty 1.0"
SRV="-t $T -c 8192 --jinja --port $P $SAMP"
DEF=(--default "sampling=card non-thinking: $SAMP (presence_penalty has no GGUF key)")
for m in "$@"; do b=$(basename "$m")
  g=$(python3 "$R/scripts/bench_guard.py" meta "$m" "${DEF[@]}" 2>&1); grc=$?
  tag=bonsai-${b%.gguf}
  FAMILIA=$R LLAMA_BIN=$BIN sh "$R/scripts/perf/bench_capped.sh" "$m" 4096 $tag -t $T -p 128 -n 32 -r 2 > /tmp/bb.out 2>&1
  brc=$?; grep -h '^{' ~/perf/logs/$tag.jsonl 2>/dev/null | python3 -c "import sys,json;print(json.dumps([json.loads(l) for l in sys.stdin]))" > /tmp/bj.json
  # server: same headroom hard cap as bench_capped.sh (MemAvailable - 1.5 GiB), no MemorySwapMax
  HARD=$(python3 -c "import sys;sys.path.insert(0,'$R/scripts');import bench_guard as b;print(b.headroom_cap_mib())")
  systemd-run --user --scope -q -p MemoryHigh=$((HARD-256))M -p MemoryMax=${HARD}M "$BIN/llama-server" -m "$m" $SRV > /tmp/bonsai-srv.log 2>&1 &
  for i in $(seq 90); do curl -sf localhost:$P/health >/dev/null && break; sleep 2; done
  hd=$(mktemp -d); HERMES_HOME=$hd sh "$R/scripts/hermes.sh" --mode single --render-only > $hd/render.txt 2>&1
  soul=$(ls $hd/SOUL.md $hd/*/SOUL.md 2>/dev/null | head -1); [ -n "$soul" ] || soul=$hd/render.txt
  python3 - "$m" "$P" "$soul" "$grc" "$brc" "$R" "$SRV" <<'PY' 
import json,sys,time,urllib.request
m,P,soul,grc,brc,R,srv=sys.argv[1:]
sys.path.insert(0,R+"/scripts")
U="http://127.0.0.1:%s/v1"%P
tools=[{"type":"function","function":{"name":"get_weather","description":"Current weather for a city","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}]
def call(sysmsg):
    body={"messages":[{"role":"system","content":sysmsg},{"role":"user","content":"What's the weather in Paris right now? Use the tool."}],"tools":tools,"max_tokens":256,"chat_template_kwargs":{"enable_thinking":False}}
    t=time.time()
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request(U+"/chat/completions",json.dumps(body).encode(),{"Content-Type":"application/json"}),timeout=900))
    except Exception as e: return {"ok":False,"err":str(e)[:120]}
    tc=d["choices"][0]["message"].get("tool_calls") or []
    ok=bool(tc) and tc[0]["function"]["name"]=="get_weather" and "paris" in tc[0]["function"]["arguments"].lower()
    return {"ok":ok,"s":round(time.time()-t,1),"prompt_tokens":d.get("usage",{}).get("prompt_tokens")}
r={"model":m.split("/")[-1],"guard_rc":int(grc),"bench_rc":int(brc),"server":srv}
try: r["bench"]=[{"test":"pp%d"%x["n_prompt"] if x["n_prompt"] else "tg%d"%x["n_gen"],"t_s":round(x["avg_ts"],2)} for x in json.load(open("/tmp/bj.json"))]
except Exception as e: r["bench"]=str(e)[:80]
r["tool_plain"]=call("You are a helpful assistant.")
r["tool_hermes"]=call(open(soul).read())
try:
    import harness2_local as L
    tasks=L.load_tasks("coding-v1"); ids=list(tasks)[:3]
    ev=L.evaluate(L.make_chat(U,"bonsai"),{"base":{"systemprompt.md":"You are a careful Python coding assistant."}},tasks,ids,log=lambda *_:None)
    r["harness2_base"]={k:v for k,v in ev["base"].items() if k!="per_task"}
except Exception as e: r["harness2_base"]="error: "+str(e)[:120]
print(json.dumps(r))
PY
  pkill -f "llama-server -m $m"; sleep 2
done
