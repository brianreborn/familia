#!/usr/bin/env bash
# Start every phone listed in graph.yaml (kind: phone with addr/user), or the names given:
#   ./android_multi_start.sh            # phone7 phone8 ...
#   ./android_multi_start.sh phone8
# Key-only SSH. Install your public key on each phone first (see MANUAL.md); no passwords.
set -euo pipefail
case "${1:-}" in -h|--help) cat <<'USAGE'
android_multi_start.sh: Start every phone in graph.yaml (kind: phone with addr/user), or the ones named.
Usage:
  ./android_multi_start.sh [PHONE...]
Example: ./android_multi_start.sh phone8
USAGE
  exit 0 ;; esac
cd "$(dirname "$0")"
if [ $# -gt 0 ]; then HOSTS=("$@"); else mapfile -t HOSTS < <(python3 scripts/android_target.py --list); fi
[ ${#HOSTS[@]} -gt 0 ] || { echo "android_multi_start.sh: no phone hosts with addr/user in graph.yaml" >&2; exit 1; }
rc=0
for h in "${HOSTS[@]}"; do
  echo "=== $h ==="
  ./android_start.sh "$h" || { echo "android_multi_start.sh: $h failed" >&2; rc=1; }
done
exit $rc
