#!/bin/sh
# FAMILIA: Configuration shell and workspace orchestrator.
# Pure POSIX /bin/sh. Sets up pinned checkouts, validates environment,
# and configures graph defaults without conflating lowram with slow CPU.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

CACHE_DIR="$ROOT/.cache"
mkdir -p "$CACHE_DIR"
chmod 700 "$CACHE_DIR" 2>/dev/null || true

INTERACTIVE=0
for arg in "$@"; do
  case "$arg" in
    -i|--interactive) INTERACTIVE=1 ;;
    --non-interactive|--batch) INTERACTIVE=0 ;;
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

sync_pin() {
  name="$1"
  rev="$2"
  origin="$3"

  target="$ROOT/$name"
  # If target does not exist locally, check if it exists in parent directory (~/green)
  if [ ! -d "$target" ] && [ -d "$ROOT/../$name" ]; then
    echo "familia: linking existing sibling checkout $name" >&2
    ln -s "$ROOT/../$name" "$target" 2>/dev/null || cp -R "$ROOT/../$name" "$target"
  fi

  if [ ! -d "$target" ]; then
    echo "familia: cloning $name from $origin..." >&2
    git clone "$origin" "$target"
  fi

  if [ -d "$target/.git" ]; then
    curr=$(git -C "$target" rev-parse HEAD 2>/dev/null || true)
    case "$curr" in
      "$rev"*) ;;
      *)
        echo "familia: syncing $name ($curr -> $rev)..." >&2
        if ! git -C "$target" fetch origin; then
          echo "familia: WARNING: fetch of $name from origin failed; trying the pin directly" >&2
        fi
        if ! git -C "$target" checkout "$rev" 2>/dev/null; then
          # Shallow or rewritten history: fetch the pin by SHA and fail loud (#21).
          echo "familia: checkout $rev failed; fetching pin by SHA..." >&2
          git -C "$target" fetch --depth 1 origin "$rev" \
            || git -C "$target" fetch origin "$rev" \
            || echo "familia: fetch of pin $name@$rev failed" >&2
          if ! git -C "$target" checkout "$rev" 2>/dev/null; then
            if [ "${FAMILIA_ALLOW_PIN_FALLBACK:-0}" = "1" ]; then
              echo "familia: WARNING: pin $name@$rev not fetchable; FAMILIA_ALLOW_PIN_FALLBACK=1 so staying on $curr" >&2
            else
              echo "familia: FATAL: pin $name@$rev not fetchable; refusing quiet HEAD fallback (set FAMILIA_ALLOW_PIN_FALLBACK=1 to override)" >&2
              exit 1
            fi
          fi
        fi
        ;;
    esac
  fi
}

# Read pins.txt
while IFS="$(printf '\t')" read -r col1 col2 col3 col4 || [ -n "$col1" ]; do
  case "$col1" in
    \#*|"") continue ;;
    node|transport) continue ;;
    llama-server__*|runtime)
      echo "familia: registered engine runtime pin: $col1 ($col2)" >&2
      engine_name="${col1#llama-server__}"
      # If this engine is requested by any ENGINE_* variable, sync it.
      req=0
      for ev in $(set | awk -F= '/^ENGINE_/ {print $2}'); do
        if [ "$ev" = "$engine_name" ]; then req=1; break; fi
      done
      if [ "$req" = 1 ]; then
        sync_pin "$col1" "$col2" "$col3"
      fi
      continue
      ;;
    *)
      # Repository pin: name <tab> revision <tab> origin <tab> role
      p_name="$col1"
      p_rev="$col2"
      p_orig="$col3"
      [ -n "$p_name" ] && [ -n "$p_rev" ] && [ -n "$p_orig" ] || continue
      sync_pin "$p_name" "$p_rev" "$p_orig"
      ;;
  esac
done < "$PINS_FILE"

# 2. Configure defaults: MCP is never disabled on slow CPU or lowram
ENV_FILE="$CACHE_DIR/familia.env"
# Pre-rename name (#16): migrate once, keep the contents.
[ -f "$ENV_FILE" ] || { [ -f "$CACHE_DIR/feeld.env" ] && mv "$CACHE_DIR/feeld.env" "$ENV_FILE"; } || true
[ -f "$ENV_FILE" ] || : > "$ENV_FILE"

# Delegate interactive settings if requested
if [ "$INTERACTIVE" = 1 ] && [ -f "$ROOT/code-bootstraps-llama.cpp/scripts/configure.sh" ]; then
  echo "familia: running interactive settings panel..." >&2
  sh "$ROOT/code-bootstraps-llama.cpp/scripts/configure.sh" || true
fi

echo "familia: configuration shell established successfully." >&2
