#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
fails=0
ok(){ echo "ok   $*"; }
bad(){ echo "FAIL $*"; fails=$((fails+1)); }

# unknown role refused
mkdir -p "$ROOT/.cache"
if sh "$ROOT/with-fleet.sh" --role no-such-role-xyz 2>"$ROOT/.cache/wf.err"; then
  bad "unknown role should fail"
else
  grep -q "not in graph" "$ROOT/.cache/wf.err" && ok "unknown role refused" || bad "wrong error"
fi

# pentest launch-test only (uses roles.pentest stub)
out=$(sh "$ROOT/with-fleet.sh" --role pentest --manifest "$ROOT/scripts/pentest-role.json" 2>&1) || rc=$?
rc=${rc-0}
printf '%s\n' "$out" | grep -q 'LAUNCH TEST ONLY' && ok "pentest launch-test only" || bad "no launch-test marker: $out"
printf '%s\n' "$out" | grep -q 'launch-test PASS' && ok "pentest launch-test PASS" || bad "no PASS"
[ "$rc" = 0 ] || bad "pentest launch-test rc=$rc"

# start-green-roomz guard
if sh "$ROOT/start-green-roomz.sh" 2>"$ROOT/.cache/sgr.err"; then
  bad "guard should exit 1"
else
  grep -q 'not deployed' "$ROOT/.cache/sgr.err" && ok "start-green-roomz guard" || bad "guard message"
fi

# android_start missing-file check now finds the files
for f in with-fleet.sh scripts/pentest-role.json start-green-roomz.sh; do
  [ -e "$ROOT/$f" ] && ok "present $f" || bad "missing $f"
done

if [ "$fails" -gt 0 ]; then echo "FAILED $fails"; exit 1; fi
echo "ALL OK"
