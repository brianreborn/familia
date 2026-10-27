#!/bin/sh
# FAMILIA: Configuration shell and workspace orchestrator.
# Pure POSIX /bin/sh. Sets up pinned checkouts, validates environment,
# and configures graph defaults without conflating lowram with slow CPU.
set -eu
case "${1:-}" in -h|--help) cat <<'USAGE'
configure.sh: Fetch or update the pinned parts listed in pins.txt (code-bootstraps, green-agentz, ...).
Usage:
  sh scripts/configure.sh [--dry-run] [-i|--interactive]
    --dry-run       list the pins and what would be cloned or checked out; change nothing
    -i, --interactive  then ask for launcher settings (port, threads, context)
Example: sh scripts/configure.sh --dry-run
USAGE
  exit 0 ;; esac

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

CACHE_DIR="$ROOT/.cache"
mkdir -p "$CACHE_DIR"
chmod 700 "$CACHE_DIR" 2>/dev/null || true

INTERACTIVE=0
DRY=0
for arg in "$@"; do
  case "$arg" in
    -i|--interactive) INTERACTIVE=1 ;;
    --non-interactive|--batch) INTERACTIVE=0 ;;
    --dry-run|-n) DRY=1 ;;
  esac
done

echo "familia: configuring topology at $ROOT" >&2

PANEL_ENV="$ROOT/code-bootstraps-llama.cpp/.cache/panel.env"
[ -f "$PANEL_ENV" ] && . "$PANEL_ENV"

# 1. Parse pins.txt and ensure sub-checkouts exist at pinned revisions
PINS_FILE="$ROOT/pins.txt"
if [ ! -f "$PINS_FILE" ]; then
  echo "familia: pins.txt not found at $PINS_FILE" >&2
  exit 1
fi

# Every pin is synced together by scripts/sync_pins.py: fetch only a missing pin, check out,
# verify HEAD, all or nothing; a checkout with local changes is never touched (#21).
if [ "$DRY" = 1 ]; then
  python3 "$ROOT/scripts/sync_pins.py" --dry-run --root "$ROOT"
  echo "familia: [dry-run] nothing changed." >&2; exit 0
fi
python3 "$ROOT/scripts/sync_pins.py" --root "$ROOT" || exit $?
FAMILIA_SYNC_DONE="$ROOT"; export FAMILIA_SYNC_DONE
# Sync again after every `git pull` of familia itself (hooks never replace one of yours).
python3 "$ROOT/scripts/sync_pins.py" --root "$ROOT" --install-hooks || true

# 2. Configure defaults: MCP is never disabled on slow CPU or lowram
ENV_FILE="$CACHE_DIR/familia.env"
# Pre-rename name (#16): migrate once, keep the contents.
[ -f "$ENV_FILE" ] || { [ -f "$CACHE_DIR/feeld.env" ] && mv "$CACHE_DIR/feeld.env" "$ENV_FILE"; } || true
[ -f "$ENV_FILE" ] || : > "$ENV_FILE"

# Delegate interactive settings if requested
if [ "$INTERACTIVE" = 1 ] && [ -f "$ROOT/code-bootstraps-llama.cpp/scripts/configure.sh" ]; then
  echo "familia: running interactive launcher settings..." >&2
  sh "$ROOT/code-bootstraps-llama.cpp/scripts/configure.sh" || true
fi

echo "familia: configuration shell established successfully." >&2
