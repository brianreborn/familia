#!/bin/sh
# run-tests.sh: run familia's unit tests. pytest is installed once into .cache/pylib (no sudo).
# Usage: sh scripts/run-tests.sh [pytest args...]
# Example: sh scripts/run-tests.sh tests/test_skills.py
# The pinned parts are synced first (scripts/sync_pins.py; licenses: warn only).
# Known pre-existing failure: test_overcommit_is_hard_error.
set -eu
case "${1:-}" in -h|--help) sed -n '2,5p' "$0" | sed 's/^# //'; exit 0 ;; esac
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}
mkdir -p .cache
if ! PYTHONPATH=.cache/pylib "$PY" -c 'import pytest' 2>/dev/null; then
  echo "run-tests: installing pytest into .cache/pylib (one time)..." >&2
  "$PY" -m pip install -q --target .cache/pylib pytest || {
    echo "run-tests: could not install pytest. Check the network, or install it: $PY -m pip install --user pytest" >&2; exit 1; }
fi
# Pinned parts first, all together (REQUIREMENTS.md R-sync; scripts/sync_pins.py).
if [ -f "$ROOT/scripts/sync_pins.py" ]; then
  python3 "$ROOT/scripts/sync_pins.py" --auto --license-gate warn || { rc=$?; echo "run-tests: the pinned parts could not be synced (see above); stopped" >&2; exit $rc; }
  FAMILIA_SYNC_DONE="$ROOT"; export FAMILIA_SYNC_DONE
fi
[ $# -gt 0 ] || set -- tests
PYTHONPATH=.cache/pylib exec "$PY" -m pytest -q -p no:cacheprovider "$@"
