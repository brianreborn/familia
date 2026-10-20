#!/bin/sh
# Pass iff pytest has no failures beyond those already failing on origin/main (cached per sha).
b="$HOME/.local/state/familia/dogfood/baseline-$(git rev-parse origin/main).txt"
if [ ! -f "$b" ]; then t=$(mktemp -d); git worktree add -q --detach "$t" origin/main
  (cd "$t" && pytest -q -p no:cacheprovider 2>&1 | sed -n 's/^FAILED \([^ ]*\).*/\1/p' | sort) > "$b"; git worktree remove --force "$t"; fi
pytest -q -p no:cacheprovider 2>&1 | sed -n 's/^FAILED \([^ ]*\).*/\1/p' | sort > /tmp/dogfood-now.$$
new=$(comm -13 "$b" /tmp/dogfood-now.$$); rm -f /tmp/dogfood-now.$$
[ -z "$new" ] || { echo "new failures: $new"; exit 1; }
