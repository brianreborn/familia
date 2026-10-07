#!/bin/sh
# FEELDZNUTTS: Super-project launcher
# Pure POSIX /bin/sh.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

# Ensure configuration / subprojects exist
if [ ! -d "$ROOT/code-bootstraps-llama.cpp" ] && [ ! -d "$ROOT/../code-bootstraps-llama.cpp" ]; then
  sh "$ROOT/scripts/configure.sh"
fi

BACKEND_START="$ROOT/code-bootstraps-llama.cpp/start.sh"
if [ ! -f "$BACKEND_START" ] && [ -f "$ROOT/../code-bootstraps-llama.cpp/start.sh" ]; then
  BACKEND_START="$ROOT/../code-bootstraps-llama.cpp/start.sh"
fi

if [ -f "$BACKEND_START" ]; then
  exec sh "$BACKEND_START" "$@"
else
  echo "feeldznutts: start.sh backend not found. Run sh scripts/configure.sh first." >&2
  exit 1
fi
