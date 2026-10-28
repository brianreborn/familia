#!/bin/sh
# Thin wrapper: ./scripts/reconnect_selfheal.sh [--probe-only|--once|--loop] [...]
# Composes with offline_improve; no models on the probe path. See docs/reconnect-selfheal.md
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$here/reconnect_selfheal.py" "$@"
