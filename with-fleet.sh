#!/bin/sh
# Thin fleet launcher (issue #15). Validates graph.yaml, resolves --role against
# the graph (agents.*, pentests.*, or roles.*), and launches that role.
# Pentest roles are launch-test only: validate → would-start → stop. Never live
# scans, exploits, or network probes.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

ROLE=""
MANIFEST=""
LAUNCH_TEST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE=${2-}; shift 2 ;;
    --role=*) ROLE=${1#*=}; shift ;;
    --manifest) MANIFEST=${2-}; shift 2 ;;
    --manifest=*) MANIFEST=${1#*=}; shift ;;
    --launch-test|--dry-run) LAUNCH_TEST=1; shift ;;
    --yes|-y) export FAMILIA_ACCEPT_LICENSES=yes; shift ;;
    -h|--help)
      echo "with-fleet.sh: validate graph.yaml, resolve a role, and launch it (pentest roles: launch-test only)."
      echo "Usage: sh with-fleet.sh --role NAME [--manifest FILE] [--launch-test|--dry-run] [--yes]"
      echo "  --launch-test, --dry-run  validate and show what would start; start nothing"
      echo "  --yes                     accept the license review without a prompt (summary still printed)"
      echo "Example: sh with-fleet.sh --role hermes --launch-test"
      exit 0 ;;
    *) echo "with-fleet.sh: unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$ROLE" ] || { echo "with-fleet.sh: --role is required. Example: sh with-fleet.sh --role hermes --launch-test (see --help)" >&2; exit 2; }

GRAPH=${GRAPH:-$ROOT/graph.yaml}
[ -f "$GRAPH" ] || { echo "with-fleet.sh: graph not found: $GRAPH" >&2; exit 1; }

echo "with-fleet.sh: validating $GRAPH" >&2
python3 "$ROOT/scripts/validate_graph.py" --graph "$GRAPH" || {
  echo "with-fleet.sh: graph validation failed; refusing to launch" >&2
  exit 1
}
if [ "$LAUNCH_TEST" = 1 ]; then
  [ ! -f "$ROOT/scripts/sync_pins.py" ] || python3 "$ROOT/scripts/sync_pins.py" --check --quiet || echo "with-fleet.sh: note: the pinned parts are behind pins.txt; a real launch syncs them first (./familia sync --dry-run)" >&2
else
  # Pinned parts first, all together (REQUIREMENTS.md R-sync; scripts/sync_pins.py).
  if [ -f "$ROOT/scripts/sync_pins.py" ]; then
    python3 "$ROOT/scripts/sync_pins.py" --auto || { rc=$?; echo "with-fleet.sh: the pinned parts could not be synced (see above); stopped" >&2; exit $rc; }
    FAMILIA_SYNC_DONE="$ROOT"; export FAMILIA_SYNC_DONE
  fi
fi

# Resolve role in graph: pentests.NAME, roles.NAME, agents.NAME (in that order).
RESOLVED=$(ROLE="$ROLE" GRAPH="$GRAPH" python3 - <<'PY'
import os, sys, yaml
g = yaml.safe_load(open(os.environ["GRAPH"]))
role = os.environ["ROLE"]
for section in ("pentests", "roles", "agents"):
    block = g.get(section) or {}
    if role in block:
        entry = block[role] or {}
        kind = section
        launch_only = bool(entry.get("launch_test_only")) or kind == "pentests" or role in ("pentest", "android-fleet")
        node = entry.get("node") or (entry.get("edges") or {}).get("model") or ""
        status = entry.get("status", "active" if kind == "agents" else "planned")
        print(f"{kind}\t{role}\t{node}\t{int(launch_only)}\t{status}")
        sys.exit(0)
# Alias: --role pentest → first pentests.* entry
if role == "pentest":
    for name, entry in (g.get("pentests") or {}).items():
        entry = entry or {}
        node = entry.get("node") or ""
        print(f"pentests\t{name}\t{node}\t1\t{entry.get('status','planned')}")
        sys.exit(0)
sys.exit(1)
PY
) || {
  echo "with-fleet.sh: role '$ROLE' is not in graph.yaml (agents/pentests/roles); refusing" >&2
  exit 1
}

kind=$(printf '%s' "$RESOLVED" | cut -f1)
name=$(printf '%s' "$RESOLVED" | cut -f2)
node=$(printf '%s' "$RESOLVED" | cut -f3)
launch_only=$(printf '%s' "$RESOLVED" | cut -f4)
status=$(printf '%s' "$RESOLVED" | cut -f5)

echo "with-fleet.sh: role=$ROLE → $kind.$name node=${node:-none} status=$status launch_test_only=$launch_only" >&2

if [ -n "$MANIFEST" ]; then
  [ -f "$MANIFEST" ] || { echo "with-fleet.sh: manifest not found: $MANIFEST" >&2; exit 1; }
  echo "with-fleet.sh: manifest $MANIFEST" >&2
  # Empty scope is required for stubs; refuse non-empty allow when launch-testing.
  if [ "$launch_only" = 1 ] || [ "$LAUNCH_TEST" = 1 ]; then
    SCOPE_ALLOW=$(MANIFEST="$MANIFEST" python3 - <<'PY'
import json, os
m = json.load(open(os.environ["MANIFEST"]))
allow = (m.get("scope") or {}).get("allow") or m.get("allow") or []
print(len(allow))
PY
)
    if [ "$SCOPE_ALLOW" != 0 ]; then
      echo "with-fleet.sh: launch-test only; manifest scope.allow must be empty (got $SCOPE_ALLOW entries)" >&2
      exit 1
    fi
  fi
fi

if [ "$launch_only" = 1 ] || [ "$LAUNCH_TEST" = 1 ]; then
  echo "with-fleet.sh: LAUNCH TEST ONLY — validate ok; not starting live tools/scans" >&2
  if [ -n "$node" ]; then
    echo "with-fleet.sh: would start node '$node' (args only, no exec):" >&2
    python3 "$ROOT/scripts/validate_graph.py" --graph "$GRAPH" --args "$node" 2>/dev/null || \
      echo "with-fleet.sh: note: --args $node not available (node planned or missing)" >&2
  fi
  echo "with-fleet.sh: launch-test PASS (stopped without exercising the role)" >&2
  exit 0
fi

# Non-pentest roles: start via hermes harness against the agent name when present.
if [ "$kind" = "agents" ]; then
  # Licenses first: show what this selection brings in (docs/licenses.md).
  python3 "$ROOT/scripts/licenses.py" gate || {
    rc=$?; echo "with-fleet.sh: licenses not accepted; nothing started. Review: python3 scripts/licenses.py review" >&2; exit $rc; }
  exec bash "$ROOT/scripts/hermes.sh" --agent "$name"   # hermes.sh is bash (pipefail)
fi

echo "with-fleet.sh: no launcher for $kind.$name (status=$status); nothing started" >&2
exit 1
