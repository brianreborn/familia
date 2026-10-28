#!/bin/sh
# Thin fleet launcher (issue #15). Validates graph.yaml, resolves --role against
# the graph (agents.*, pentests.*, or roles.*), and launches that role.
# Guardian/defender (pentest) roles: seatbelts on by default — launch-test path
# validates → would-start → stop. Tools stay dual-disabled until the operator widens.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

ROLE=""
MANIFEST=""
LAUNCH_TEST=0
OPERATOR_START=0
while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE=${2-}; shift 2 ;;
    --role=*) ROLE=${1#*=}; shift ;;
    --manifest) MANIFEST=${2-}; shift 2 ;;
    --manifest=*) MANIFEST=${1#*=}; shift ;;
    --launch-test|--dry-run) LAUNCH_TEST=1; shift ;;
    --operator-start) OPERATOR_START=1; shift ;;
    --yes|-y) export FAMILIA_ACCEPT_LICENSES=yes; shift ;;
    -h|--help)
      echo "with-fleet.sh: validate graph.yaml, resolve a role, and launch it (guardian/defender: seatbelts on by default)."
      echo "Usage: sh with-fleet.sh --role NAME [--manifest FILE] [--launch-test|--dry-run] [--operator-start] [--yes]"
      echo "  --launch-test, --dry-run  validate and show what would start; start nothing"
      echo "  --operator-start         guardian only: after confirm, start the model node (tools still empty)"
      echo "  --yes                     accept the license review without a prompt (summary still printed)"
      echo "Example: sh with-fleet.sh --role hermes --launch-test"
      echo "Example: FAMILIA_OPERATOR_CONFIRM=yes sh with-fleet.sh --role guardian --operator-start"
      exit 0 ;;
    *) echo "with-fleet.sh: unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$ROLE" ] || { echo "with-fleet.sh: --role is required. Example: sh with-fleet.sh --role hermes --launch-test (see --help)" >&2; exit 2; }

# Guardian/defender is the public name for the owned-fleet pentest node flavor.
case "$ROLE" in
  guardian|defender|pentest) ROLE=fleet ;;
esac

GRAPH=${GRAPH:-$ROOT/graph.yaml}
[ -f "$GRAPH" ] || { echo "with-fleet.sh: graph not found: $GRAPH" >&2; exit 1; }

echo "with-fleet.sh: validating $GRAPH (schema)" >&2
python3 "$ROOT/scripts/validate_graph.py" --graph "$GRAPH" --no-files || {
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

# Host-scoped artifact check when the role names a node (skip other hosts' missing GGUFs).
if [ -n "$node" ]; then
  NODE_HOST=$(NODE="$node" GRAPH="$GRAPH" python3 - <<'PY'
import os, yaml
g = yaml.safe_load(open(os.environ["GRAPH"]))
n = (g.get("nodes") or {}).get(os.environ["NODE"]) or {}
print(n.get("host") or "")
PY
)
  if [ -n "$NODE_HOST" ]; then
    # Launch-test seatbelt: schema + host scope without requiring sibling hosts' GGUFs
    # (e.g. angel Nanbeige absent on Ubuntu laptop must not barricade guardian smoke).
    if [ "$LAUNCH_TEST" = 1 ] || [ "$launch_only" = 1 ]; then
      echo "with-fleet.sh: launch-test artifact check for host $NODE_HOST (node $node; --no-files)" >&2
      python3 "$ROOT/scripts/validate_graph.py" --graph "$GRAPH" --host "$NODE_HOST" --no-files || {
        echo "with-fleet.sh: host-scoped schema validation failed; refusing launch-test" >&2
        exit 1
      }
    else
      echo "with-fleet.sh: validating artifacts for host $NODE_HOST (node $node)" >&2
      python3 "$ROOT/scripts/validate_graph.py" --graph "$GRAPH" --host "$NODE_HOST" || {
        echo "with-fleet.sh: host-scoped validation failed; refusing to launch" >&2
        exit 1
      }
    fi
  fi
fi

if [ "$OPERATOR_START" = 1 ]; then
  if [ "$kind" != "pentests" ]; then
    echo "with-fleet.sh: --operator-start is only for pentests.* roles (got $kind.$name)" >&2
    exit 2
  fi
  if [ "$LAUNCH_TEST" = 1 ]; then
    echo "with-fleet.sh: refuse --operator-start together with --launch-test" >&2
    exit 2
  fi
  CONFIRM=${FAMILIA_OPERATOR_CONFIRM:-}
  if [ "$CONFIRM" != "yes" ] && [ "$CONFIRM" != "YES" ]; then
    echo "with-fleet.sh: operator confirm required for guardian start." >&2
    echo "with-fleet.sh: owned-fleet scope only; starts the model node; tools.allow stays empty (seatbelt)." >&2
    echo "with-fleet.sh: re-run with FAMILIA_OPERATOR_CONFIRM=yes" >&2
    exit 2
  fi
  CHECK=$(NAME="$name" GRAPH="$GRAPH" python3 - <<'PY'
import os, sys, yaml
g = yaml.safe_load(open(os.environ["GRAPH"]))
p = (g.get("pentests") or {}).get(os.environ["NAME"]) or {}
if p.get("requires_operator_confirm") is not True:
    print("missing_confirm"); sys.exit(0)
tools = ((p.get("tools") or {}).get("allow")) or []
node = p.get("node") or ""
status = p.get("status") or "planned"
print("ok\t%s\t%s\t%d" % (node, status, len(tools)))
PY
)
  case "$CHECK" in
    missing_confirm)
      echo "with-fleet.sh: pentests.$name requires_operator_confirm must be true" >&2
      exit 1 ;;
  esac
  onode=$(printf '%s' "$CHECK" | cut -f2)
  ostatus=$(printf '%s' "$CHECK" | cut -f3)
  ntools=$(printf '%s' "$CHECK" | cut -f4)
  [ -n "$onode" ] || { echo "with-fleet.sh: pentests.$name has no node" >&2; exit 1; }
  if [ "$ostatus" != "active" ]; then
    echo "with-fleet.sh: guardian node still planned (status=$ostatus) — fetch weights, measure sha, set active, retry" >&2
    echo "with-fleet.sh: helper: python3 scripts/activate_guardian_weights.py   # docs/guardian-weights.md" >&2
    echo "with-fleet.sh: fetch: scripts/add-model.sh --fetch RavichandranJ/Dolphin3-Cyber-8B-GGUF --quant Q2_K --role pentest --accept-licenses" >&2
    echo "with-fleet.sh: documented LAUNCH_FAILED fix: weights absent (LF_MODEL_FILE); see docs/guardian-weights.md" >&2
    exit 1
  fi
  if [ "$ntools" != "0" ]; then
    echo "with-fleet.sh: refusing operator-start while tools.allow is non-empty ($ntools entries)." >&2
    echo "with-fleet.sh: keep tools.allow: [] for model-only start (REQUIREMENTS double-disable)." >&2
    exit 1
  fi
  python3 "$ROOT/scripts/licenses.py" gate || {
    rc=$?; echo "with-fleet.sh: licenses not accepted; nothing started" >&2; exit $rc; }
  echo "with-fleet.sh: OPERATOR START — guardian model node only ($onode); owned-fleet; tools.allow empty (seatbelt)" >&2
  export DETACH_MODE="${DETACH_MODE:-screen-attached}"
  exec sh "$ROOT/scripts/serve.sh" "$onode"
fi


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
  echo "with-fleet.sh: LAUNCH TEST (guardian seatbelts on) — validate ok; not starting tools/scans" >&2
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
  # fail closed: hermes talks to :9931, which needs the instance key (familia_auth; serve.sh creates it)
  python3 "$ROOT/scripts/familia_auth.py" has-key || {
    echo "with-fleet.sh: no instance API key found (start the server once: scripts/serve.sh, or set API_KEY_FILE); nothing started" >&2; exit 1; }
  exec bash "$ROOT/scripts/hermes.sh" --agent "$name"   # hermes.sh is bash (pipefail)
fi

echo "with-fleet.sh: no launcher for $kind.$name (status=$status); nothing started" >&2
exit 1
