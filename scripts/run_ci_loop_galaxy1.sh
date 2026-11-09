#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/green/.gemini/antigravity/scratch/familia"
cd "$REPO_DIR"

# Loop for galaxy1 (simulated)
while true; do
  TIMESTAMP=$(date -u +"%Y%m%d%H%M%S")
  LOG="/usr/home/recovery/ci_loop_galaxy1_${TIMESTAMP}.log"
  echo "--- CI run galaxy1 $TIMESTAMP start ---" | tee -a "$LOG"
  pytest -q test_graph_router.py test_ram_safety.py test_graph_types.py test_start_graph.py | tee -a "$LOG"
  echo "--- CI run galaxy1 $TIMESTAMP end $(date -u) ---" | tee -a "$LOG"
  sleep 300
done
