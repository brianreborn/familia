#!/bin/bash
# Unattended centos10-bigram sweep. Log: ~/perf/driver.log. One big model on disk at a time.
cd ~/models; L=~/perf/driver.log; R=~/perf/results.md; F=~/repositories/familia
log(){ echo "$(date +%H:%M) $*" | tee -a $L >&2; }
# Resolve GGUF for repo + path pattern. Prefer a verified local file (registry sha256 or
# last-known HF LFS oid) so a transient HF tree failure does not skip an on-disk model (#107).
fetch(){ # repo pattern -> prints filename
  local repo=$1 pat=$2
  local oid_dir=${OID_CACHE_DIR:-$HOME/perf/oids}
  local oid_file="$oid_dir/${repo//\//--}--${pat}"
  local reg="$F/registry/models/${repo//\//--}--${pat}.json"
  local known="" localf="" got="" path="" oid="" i

  if [ -f "$reg" ]; then
    known=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('sha256') or '')" "$reg" 2>/dev/null || true)
  fi
  if [ -z "$known" ] && [ -f "$oid_file" ]; then
    known=$(tr -d '[:space:]' < "$oid_file")
  fi

  if [ -f "${pat}.gguf" ]; then
    localf="${pat}.gguf"
  else
    localf=""
    for _cand in ./*"${pat}"*.gguf; do
      [ -f "$_cand" ] || continue
      case "$_cand" in *mmproj*) continue ;; esac
      localf=${_cand#./}
      break
    done
  fi
  if [ -n "$localf" ] && [ -n "$known" ] && [ "$(sha256sum "$localf" | cut -d' ' -f1)" = "$known" ]; then
    log "LOCAL $localf"
    echo "$localf"
    return 0
  fi

  got=""
  export FETCH_PAT=$pat
  for i in 1 2 3 4 5; do
    got=$(curl -sf "https://huggingface.co/api/models/${repo}/tree/main" | python3 -c '
import json, os, sys
pat = os.environ["FETCH_PAT"]
for x in json.load(sys.stdin):
  p = x.get("path") or ""
  if p.endswith(".gguf") and pat in p and "mmproj" not in p:
    oid = (x.get("lfs") or {}).get("oid") or ""
    print(p, oid)
    break
' 2>/dev/null) && [ -n "$got" ] && break
    log "tree retry $i $repo"
    sleep $((10 * i))
    got=""
  done
  unset FETCH_PAT
  # shellcheck disable=SC2086
  set -- $got
  path=$1; oid=$2
  if [ -z "$path" ] || [ -z "$oid" ]; then
    log "NOFILE $repo"
    return 1
  fi
  mkdir -p "$oid_dir"
  printf '%s\n' "$oid" > "$oid_file"

  if [ -f "$path" ] && [ "$(sha256sum "$path" | cut -d' ' -f1)" = "$oid" ]; then
    log "LOCAL $path"
    echo "$path"
    return 0
  fi

  for i in 1 2 3 4 5; do
    curl -sfL -C - -o "$path" "https://huggingface.co/${repo}/resolve/main/${path}" && break
    log "dl retry $i $path rc=$?"
    sleep 20
  done
  [ "$(sha256sum "$path" | cut -d' ' -f1)" = "$oid" ] || { log "SHA-MISMATCH $path"; return 1; }
  echo "$path"
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
