#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/tmp/familia"
cd "$REPO_DIR"
# Ensure a recovery log dir exists
LOG_DIR="/tmp/familia/recovery"
mkdir -p "$LOG_DIR"

# Loop: run pytest, store log, wait 5 minutes
while true; do
  TIMESTAMP=$(date -u +"%Y%m%d%H%M%S")
  LOG="${LOG_DIR}/ci_loop_${TIMESTAMP}.log"
  echo "--- CI run $TIMESTAMP start ---" | tee -a "$LOG"
  pytest -q test_graph_router.py test_ram_safety.py test_graph_types.py test_start_graph.py | tee -a "$LOG"
  echo "--- CI run $TIMESTAMP end $(date -u) ---" | tee -a "$LOG"
  sleep 300
done
