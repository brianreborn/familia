#!/bin/bash
# Unattended centos10-bigram sweep. Log: ~/perf/driver.log. One big model on disk at a time.
cd ~/models; L=~/perf/driver.log; R=~/perf/results.md; F=~/repositories/familia
log(){ echo "$(date +%H:%M) $*" | tee -a $L >&2; }
fetch(){ # repo pattern -> prints filename
  f=$(curl -sf "https://huggingface.co/api/models/$1/tree/main" | python3 -c "
import sys,json
for x in json.load(sys.stdin):
  if x['path'].endswith('.gguf') and '$2' in x['path'] and 'mmproj' not in x['path']: print(x['path'],x['lfs']['oid']);break")
  set -- $1 $f; [ -z "$2" ] && { log "NOFILE $1"; return 1; }
  for i in 1 2 3 4 5; do curl -sfL -C - -o "$2" "https://huggingface.co/$1/resolve/main/$2" && break; log "dl retry $i $2 rc=$?"; sleep 20; done
  [ "$(sha256sum "$2"|cut -d' ' -f1)" = "$3" ] || { log "SHA-MISMATCH $2"; return 1; }
  echo "$2"
}
sweep(){ m=$1; tag=$2
  lab=$(python3 $F/scripts/bench_guard.py label $m); log "== $tag [$lab] $(du -h $m|cut -f1)"
  ~/perf/bench.sh $m 16384 $tag-t -t 2,4 -p 512 -n 64 -r 1 -lm none >> $R 2>&1
  ~/perf/bench.sh $m 16384 $tag-ub -t 4 -p 512 -n 0 -ub 128,512 -r 1 -lm none,mmap >> $R 2>&1
  ~/perf/bench.sh $m 16384 $tag-d16k -t 4 -p 0 -n 32 -d 16384 -ctk f16,q8_0 -ctv f16,q8_0 -fa 1 -r 1 -lm none >> $R 2>&1
  P=$(python3 -c "
import json,glob
v=[json.loads(l) for f in glob.glob('$HOME/perf/logs/$tag-t.jsonl') for l in open(f)]
v=[d['avg_ts'] for d in v if d['n_gen']>0]; print(max(v) if v else 0)")
  python3 $F/scripts/plan_placement.py $F/registry/links/centos10-bigram.jsonl $m --active-frac ${AF[$tag]:-1} --measured $P | grep cpu | sed "s/^/PLAN $tag /" | tee -a $L >> $R
  grep -E "PROCESS-DEATH|GUARD-FAIL" $R | tail -3 >> $L
}
declare -A AF=([q35-9b]=1 [gptoss20b]=0.172 [lfm8b]=0.176 [lfm24b]=0.102 [q36-35b]=0.0865 [gemma4-26b]=0.151)
log START
f=Qwen3.5-9B-Q4_K_M.gguf; fetch unsloth/Qwen3.5-9B-GGUF Qwen3.5-9B-Q4_K_M >/dev/null && { sweep $f q35-9b; rm -f $f; }
sweep gpt-oss-20b-MXFP4.gguf gptoss20b; rm -f gpt-oss-20b-MXFP4.gguf
f=$(fetch LiquidAI/LFM2.5-8B-A1B-GGUF LFM2.5-8B-A1B-Q4_K_M) && { sweep $f lfm8b
  log "== concurrency lfm8b t2 + coder t1 + general t1"
  echo "### concurrency" >> $R
  taskset -c 0,1 ~/perf/bench.sh $f 8000 conc-lfm8b -t 2 -p 256 -n 128 -r 3 -lm none >> $R 2>&1 &
  taskset -c 2 ~/perf/bench.sh Qwen3.5-2B-Q4_K_M.gguf 3500 conc-coder -t 1 -p 256 -n 128 -r 3 -lm none >> $R 2>&1 &
  taskset -c 3 ~/perf/bench.sh LFM2.5-1.2B-Instruct-Q4_K_M.gguf 2500 conc-general -t 1 -p 256 -n 128 -r 5 -lm none >> $R 2>&1 &
  wait; rm -f $f; }
for spec in "LiquidAI/LFM2.5-24B-A2B-GGUF LFM2.5-24B-A2B-Q4_K_M lfm24b" "unsloth/Qwen3.6-35B-A3B-GGUF UD-Q3_K_S q36-35b" "ggml-org/gemma-4-26B-A4B-it-GGUF Q4_0 gemma4-26b"; do
  set -- $spec; f=$(fetch $1 $2) && { sweep $f $3; rm -f $f; }
done
log "suite+push"
cd $F && git add registry/links; sh scripts/run-tests.sh -q >> $L 2>&1 && git fetch -q && git rebase -q origin/main && git push -q origin HEAD:main && log "pushed $(git log --oneline -1)"
log DONE; df -h /home | tail -1 >> $L
