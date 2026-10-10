#!/usr/bin/env bash
# Launch hermes-agent against the familia graph (see scripts/hermes_harness.py).
# Usage: scripts/hermes.sh [--agent NAME] [--render-only] [--selftest-compaction] [-- hermes args...]
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/hermes_harness.py "$@"
