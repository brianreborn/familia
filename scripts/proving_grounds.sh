#!/bin/sh
# proving_grounds.sh: graded progress on the top-level "proving grounds".
# These are NOT pass/fail tests. They are aspirational, environment/fleet-dependent,
# multi-step runs; familia operates without them fully succeeding. Each ground reports
# steps reached N/M (counting its "ok"/"FAIL" lines) and this script exits 0 unless
# --strict is given. Real pass/fail tests live in tests/ (pytest) and gate CI.
set -u
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
STRICT=0
case "${1:-}" in
  -h|--help)
    cat <<'USAGE'
Usage: sh scripts/proving_grounds.sh [--strict] [GROUND...]

◆ Proving grounds (graded, not pass/fail):
  proving_grounds/fleet_wiring.sh     fleet wiring: roles, launch-tests, guards
  proving_grounds/nexus_localhost.sh  SSH nexus on localhost (needs sudo/useradd/sshd)
  proving_grounds/bt_loopback.sh      private BitTorrent loopback (needs aria2c)

Reports "steps reached N/M" per ground. Exit 0 always, unless --strict
(then non-zero if any ground is short of M/M).

Example:
  sh scripts/proving_grounds.sh
  ./familia   # then pick ◆ Proving grounds (graded)
USAGE
    exit 0 ;;
  --strict) STRICT=1; shift ;;
esac
GROUNDS=${*:-"proving_grounds/fleet_wiring.sh proving_grounds/nexus_localhost.sh proving_grounds/bt_loopback.sh"}
LOG=$ROOT/.cache/proving-grounds; mkdir -p "$LOG"
short=0; total=0
printf '◆ Proving grounds — graded progress (not pass/fail)\n\n'
for g in $GROUNDS; do
  total=$((total+1))
  name=$(basename "$g" .sh)
  bash "$ROOT/$g" >"$LOG/$name.log" 2>&1; rc=$?
  ok=$(grep -cE '^ok( |$)' "$LOG/$name.log"); bad=$(grep -cE '^FAIL ' "$LOG/$name.log")
  m=$((ok+bad))
  if [ "$m" = 0 ]; then  # ground without step lines: one step, reached iff rc=0
    m=1; [ "$rc" = 0 ] && ok=1 || ok=0
  fi
  if [ "$ok" = "$m" ] && [ "$rc" = 0 ]; then mark='●'; else mark='◐'; short=$((short+1)); fi
  printf '  %s %-18s steps reached %d/%d  (rc=%d, log .cache/proving-grounds/%s.log)\n' "$mark" "$name" "$ok" "$m" "$rc" "$name"
done
printf '\n%d of %d proving grounds fully reached.\n' $((total-short)) "$total"
[ "$STRICT" = 1 ] && [ "$short" != 0 ] && exit 1
exit 0
