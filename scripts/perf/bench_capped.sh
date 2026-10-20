#!/bin/sh
# bench.sh MODEL CAP_MIB TAG [llama-bench args...]  -- nice 19, cgroup MemoryMax, bench_guard first
M=$1; CAP=$2; TAG=$3; shift 3
F=~/repositories/familia; B=$F/code-bootstraps-llama.cpp/build-linux-x86_64/bin
L=~/perf/logs; mkdir -p $L
python3 $F/scripts/bench_guard.py meta $M --default "sampling=llama-bench is greedy-free (no sampling; pp/tg timing only)" --default "chat_template=none used by llama-bench" > $L/$TAG.meta 2>&1 || { echo "GUARD-FAIL $TAG"; cat $L/$TAG.meta; exit 3; }
python3 $F/scripts/bench_guard.py meta $M --json > $L/$TAG.meta.json
# CAP (peak+margin) is a soft MemoryHigh hint only; hard MemoryMax = MemAvailable - 1.5 GiB reserve.
HARD=$(python3 -c "import sys;sys.path.insert(0,'$F/scripts');import bench_guard as b;print(b.headroom_cap_mib())")
[ "$HARD" -lt "$CAP" ] && HARD=$CAP
USED=$(python3 -c "import sys;sys.path.insert(0,'$F/scripts');import bench_guard as b;print(b.threads_in_use())")
[ "$USED" -ge "$(nproc)" ] && echo "WARN thread budget: $USED threads already in use on $(nproc) cores"
/usr/bin/time -v systemd-run --user --scope -q -p MemoryHigh=$((HARD-256))M -p MemoryMax=${HARD}M -p MemorySwapMax=0 nice -n ${NICE:-0} $B/llama-bench -m $M -o jsonl "$@" > $L/$TAG.jsonl 2> $L/$TAG.err
rc=$?; rss=$(grep "Maximum resident" $L/$TAG.err | awk '{print $NF}')
echo "$TAG rc=$rc maxrss_kib=$rss"
[ $rc -ne 0 ] && { echo "PROCESS-DEATH $TAG rc=$rc"; tail -5 $L/$TAG.err; }
python3 -c "
import json,sys
for l in open('$L/$TAG.jsonl'):
  d=json.loads(l); print('  t=%s ub=%s pp=%s tg=%s d=%s ctk=%s lm=%s -> %.2f t/s'%(d['n_threads'],d['n_ubatch'],d['n_prompt'],d['n_gen'],d.get('n_depth'),d['type_k'],d.get('load_mode',d.get('use_mmap')),d['avg_ts']))"
