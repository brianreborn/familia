#!/bin/sh
# Pass iff pytest has no failures beyond those already failing on origin/main (cached per sha).
# FAMILIA_SYNC=0: worktree add must not run pin-sync into the scratch tree (#111).
export FAMILIA_SYNC=0
b="$HOME/.local/state/familia/dogfood/baseline-$(git rev-parse origin/main).txt"
if [ ! -f "$b" ]; then t=$(mktemp -d); git worktree add -q --detach "$t" origin/main
  (cd "$t" && now=$(umask 077; mktemp "${TMPDIR:-/tmp}/dogfood-now.XXXXXX") || exit 1
pytest -q -p no:cacheprovider 2>&1 | sed -n 's/^FAILED \([^ ]*\).*/\1/p' | sort) > "$b"; git worktree remove --force "$t"; fi
now=$(umask 077; mktemp "${TMPDIR:-/tmp}/dogfood-now.XXXXXX") || exit 1
pytest -q -p no:cacheprovider 2>&1 | sed -n 's/^FAILED \([^ ]*\).*/\1/p' | sort > "$now"
new=$(comm -13 "$b" "$now"); rm -f "$now"
[ -z "$new" ] || { echo "new failures: $new"; exit 1; }
