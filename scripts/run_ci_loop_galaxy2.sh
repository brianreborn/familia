#!/usr/bin/env bash
set -euo pipefail

# CI loop for a simulated Galaxy host
while true; do
  TIMESTAMP=$(date -u +"%Y%m%d%H%M%S")
  LOG="/home/green/recovery/ci_loop_galaxy2_${TIMESTAMP}.log"
  echo "--- CI run galaxy2 $TIMESTAMP start ---" | tee -a "$LOG"
  pytest -q test_graph_router.py test_ram_safety.py test_graph_types.py test_start_graph.py | tee -a "$LOG"
  echo "--- CI run galaxy2 $TIMESTAMP end $(date -u) ---" | tee -a "$LOG"
  sleep 300
done
