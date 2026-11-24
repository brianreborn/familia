#!/usr/bin/env sh
# Thin wrapper — see scripts/activate_guardian_weights.py
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${PYTHON:-python3}" "$HERE/activate_guardian_weights.py" "$@"
