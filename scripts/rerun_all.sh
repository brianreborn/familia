#!/bin/sh
# rerun_all.sh: redo all 2026-10-19 results invalidated by the memcg cap bug (#95). Not auto-started.
# Order: bench (per model, headroom cap) -> launch matrix -> hermes / Harness² harness runs. Logs to ~/perf/rerun-$(date +%F).
set -e; F=$(cd "$(dirname "$0")/.." && pwd); M=${MODELS:-$HOME/models}; O=$HOME/perf/rerun-$(date +%F); mkdir -p "$O"
T=${THREADS:-$(nproc)}
for g in "$M"/*.gguf; do n=$(basename "$g" .gguf)
  NICE=10 sh "$F/scripts/perf/bench_capped.sh" "$g" 1024 "rerun-$n" -t "$T" -p 512 -n 64 -r 2 -lm none,mmap >> "$O/bench.txt" 2>&1 || echo "FAIL $n" >> "$O/bench.txt"
done
python3 "$F/scripts/launch_matrix.py" --models "$M" --threads "$T" --timeout 300 --out "$O/launch_matrix.jsonl" ${BIN_DIR:+--bin-dir "$BIN_DIR"} >> "$O/launch_matrix.txt" 2>&1 || true
[ -n "$HARNESS_MODEL" ] && sh "$F/scripts/perf/harness_driver.sh" "$HARNESS_MODEL" >> "$O/harness.txt" 2>&1 || true
echo "done -> $O; check ~/.local/state/familia/kills.log"
