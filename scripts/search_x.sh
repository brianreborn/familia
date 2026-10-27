#!/bin/sh
# search_x.sh: Search my X / Twitter posts via Agent-Reach (honest about setup state).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}
GUM=$(command -v gum || true)
YES=0
QUERY=""

say() { printf 'search-x: %s\n' "$*"; }
die() { printf 'search-x: error: %s\n' "$1" >&2; exit "${2:-1}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --query|-q) QUERY=${2-}; shift ;;
    -h|--help)
      printf 'Usage: sh scripts/search_x.sh [--query TEXT] [--yes]\n'; exit 0 ;;
    *) die "unknown arg $1" 2 ;;
  esac
  shift
done

can_prompt() { [ -t 0 ] && [ "${FAMILIA_NO_TTY:-}" != 1 ]; }

confirm() {
  [ "$YES" = 1 ] && return 0
  if [ -n "$GUM" ] && can_prompt; then
    gum confirm "$1"
  elif can_prompt; then
    printf '%s [y/N] ' "$1" >&2
    read -r a || return 1
    case "$a" in y|Y|yes|YES) return 0 ;; esac
    return 1
  else
    return 1
  fi
}

# 1) Pin checkout
if [ ! -d "$ROOT/agent-reach/agent_reach" ]; then
  say "Agent-Reach pin is not checked out yet."
  say "Next real action: sync the pin, then come back."
  if confirm "Run: python3 scripts/sync_pins.py (brings agent-reach)?"; then
    "$PY" "$ROOT/scripts/sync_pins.py" || die "sync_pins failed" 1
  else
    say "Skipped. When ready: python3 scripts/sync_pins.py"
    exit 0
  fi
fi

# 2) Status
say "Agent-Reach status:"
"$PY" "$ROOT/scripts/agent_reach.py" status || true

# 3) Opt hermes in if graph has no reaches yet (best-effort)
if ! "$PY" "$ROOT/scripts/agent_reach.py" status 2>/dev/null | grep -q 'agent-reach'; then
  say "No agent is opted into Agent-Reach yet."
  if confirm "Enable Agent-Reach for agent 'hermes'?"; then
    "$PY" "$ROOT/scripts/agent_reach.py" enable --agent hermes || die "enable failed" 1
  else
    say "Skipped enable. Next: python3 scripts/agent_reach.py enable --agent hermes"
    exit 0
  fi
fi

# 4) twitter-cli / cookies
HAS_TWITTER=0
if command -v twitter >/dev/null 2>&1; then
  HAS_TWITTER=1
fi
if [ "$HAS_TWITTER" != 1 ]; then
  say "twitter-cli is not on PATH (needed for X search)."
  say "Next real action (pick one):"
  say "  pipx install twitter-cli"
  say "  uv tool install twitter-cli"
  say "  (from agent-reach pin) python3 -m agent_reach.cli install --channels=twitter"
  if confirm "Try: python3 -m agent_reach.cli install --channels=twitter (from pin)?"; then
    ( cd "$ROOT/agent-reach" && "$PY" -m agent_reach.cli install --channels=twitter ) || \
      say "install returned non-zero — follow the printed next step, then re-run Search my X."
  else
    exit 0
  fi
fi

# Re-check
if ! command -v twitter >/dev/null 2>&1; then
  say "twitter still not on PATH. Install twitter-cli, then re-run this goal."
  exit 0
fi

# Cookies / env
if [ -z "${TWITTER_AUTH_TOKEN:-}" ] || [ -z "${TWITTER_CT0:-}" ]; then
  say "TWITTER_AUTH_TOKEN / TWITTER_CT0 are not set in this shell."
  say "Next real action: configure cookies (you paste them; familia never stores them for you):"
  say "  (cd agent-reach && python3 -m agent_reach.cli configure twitter-cookies)"
  say "Then export TWITTER_AUTH_TOKEN and TWITTER_CT0 in this shell, or use agent-reach's stored config."
  if confirm "Open twitter-cookies configure now?"; then
    ( cd "$ROOT/agent-reach" && "$PY" -m agent_reach.cli configure twitter-cookies ) || true
  else
    say "Skipped. Re-run Search my X after cookies are configured."
    exit 0
  fi
fi

# Query
if [ -z "$QUERY" ]; then
  if [ -n "$GUM" ] && can_prompt; then
    QUERY=$(gum input --header "X/Twitter search query (your posts: from:YOUR_HANDLE …)" --placeholder 'from:BrianReborn_alt')
  elif can_prompt; then
    printf 'Search query (e.g. from:BrianReborn_alt keyword): ' >&2
    read -r QUERY || true
  fi
fi
[ -n "$QUERY" ] || die "need a search query" 2

# Optional: ask protomodel to refine the query (best-effort, never required)
if curl -sf --connect-timeout 1 http://127.0.0.1:8080/v1/models >/dev/null 2>&1 \
   || curl -sf --connect-timeout 1 http://127.0.0.1:9931/v1/models >/dev/null 2>&1; then
  if can_prompt && confirm "Ask the protomodel to refine this query first?"; then
    say "(protomodel tip — paste a refined query if you like; Enter keeps yours)"
    printf '%s\n' "Refine this X search query for twitter-cli. Reply with ONLY the query string: $QUERY" \
      | sh "$ROOT/scripts/proto_chat.sh" --no-start 2>/dev/null | sed -n 's/^proto> //p' | head -1 | {
        read -r refined || true
        if [ -n "${refined:-}" ]; then
          say "protomodel suggested: $refined"
          if [ -n "$GUM" ]; then
            QUERY=$(gum input --header "Query to run" --value "$refined")
          else
            QUERY=$refined
          fi
        fi
      }
  fi
fi

say "Running: twitter search $(printf '%q' "$QUERY") -n 10"
twitter search "$QUERY" -n 10 || {
  say "twitter search failed. Common fix: set TWITTER_AUTH_TOKEN + TWITTER_CT0, or:"
  say "  agent-reach configure twitter-cookies"
  exit 1
}
