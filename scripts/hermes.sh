#!/usr/bin/env bash
# Launch hermes-agent from the familia graph. Two modes (scripts/hermes_modes.py):
#   graph (default)        the agent's aliases + escalation proxy where declared
#   single --model NODE    one node, its own HERMES_HOME, no router (64K floor enforced)
# `hermes.sh harness2 ...` is the Harness² review CLI (scripts/harness2.py); it launches nothing.
# Usage: scripts/hermes.sh [--mode graph|single] [--model NODE] [--agent NAME] [--self-improve]
#                          [--render-only] [--selftest-compaction] [--escalate ...] [-- hermes args...]
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" = harness2 ]; then shift; exec python3 scripts/harness2.py "$@"; fi
exec python3 scripts/hermes_modes.py "$@"
