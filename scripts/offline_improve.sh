#!/bin/sh
# Thin wrapper: ./scripts/offline_improve.sh [--check-only|--once|--loop] [...]
# Or: ./familia-monitor offline-improve  (see scripts/monitor.sh note)
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$here/.." && pwd)
exec python3 "$here/offline_improve.py" "$@"
