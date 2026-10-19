#!/bin/sh
# run-tests.sh: run familia's unit tests. pytest is installed once into .cache/pylib (no sudo).
# Usage: sh scripts/run-tests.sh [pytest args...]
# Example: sh scripts/run-tests.sh tests/test_skills.py
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
[ $# -gt 0 ] || set -- tests
PYTHONPATH=.cache/pylib exec "$PY" -m pytest -q -p no:cacheprovider "$@"
