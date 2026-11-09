#!/bin/sh
# Pass iff pytest has no failures beyond those already failing on origin/main (cached per sha).
# FAMILIA_SYNC=0: worktree add must not run pin-sync into the scratch tree (#111).
export FAMILIA_SYNC=0
b="$HOME/.local/state/familia/dogfood/baseline-$(git rev-parse origin/main).txt"
t=""; now=$(umask 077; mktemp) || exit 1
cleanup() { [ -n "$t" ] && git worktree remove --force "$t" 2>/dev/null; rm -f -- "$now"; }
trap cleanup EXIT; trap 'exit 1' INT TERM HUP
if [ ! -f "$b" ]; then t=$(umask 077; mktemp -d) || exit 1; git worktree add -q --detach "$t" origin/main
  (cd "$t" && pytest -q -p no:cacheprovider 2>&1 | sed -n 's/^FAILED \([^ ]*\).*/\1/p' | sort) > "$b"; fi
pytest -q -p no:cacheprovider 2>&1 | sed -n 's/^FAILED \([^ ]*\).*/\1/p' | sort > "$now"
new=$(comm -13 "$b" "$now")
[ -z "$new" ] || { echo "new failures: $new"; exit 1; }
