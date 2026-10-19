#!/usr/bin/env bash
# Offline checklist driver — prints commands; does not start long servers unless RUN=1.
set -euo pipefail
case "${1:-}" in -h|--help) cat <<'USAGE'
offline-test-plan.sh: Print the offline test checklist and run the quick parts; RUN=1 also runs live steps.
Usage:
  bash scripts/offline-test-plan.sh
Example: RUN=1 bash scripts/offline-test-plan.sh
USAGE
  exit 0 ;; esac
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "== familia offline test plan (see docs/offline-test-plan.md) =="
echo "Method: coarse binary search; efficiency over dense accuracy."
echo
echo "-- unit: escalation --"
python3 -m pytest tests/test_escalation.py tests/test_escalation_proxy.py -q || true
echo
echo "-- graph validate --"
python3 scripts/validate_graph.py 2>/dev/null || python3 -c "import validate_graph" 2>/dev/null || \
  python3 scripts/validate_graph.py --help 2>/dev/null | head -5 || echo "(run your usual graph validate)"
echo
if [[ "${RUN:-0}" == "1" ]]; then
  echo "-- hermes selftest-compaction (live) --"
  python3 scripts/hermes_harness.py --selftest-compaction
else
  echo "Set RUN=1 to execute hermes --selftest-compaction and other live steps."
  echo "Manual: #40 Vulkan ngl0, #41 cache reuse, #44 qodesh-resident, #43 swapfile paste."
fi
