#!/bin/sh
# kill-watch.sh: follow kernel+system+user journals, log every process kill with its cause.
# Causes: cgroup-memmax (memcg limit; scope limit printed), kernel-oom (global), systemd-oomd,
# earlyoom, familia-cap (our launcher caps), watchdog. Output: ${FAMILIA_KILL_LOG:-~/.local/state/familia/kills.log}
# Read-only. Run: systemd-run --user --unit=familia-kill-watch scripts/watchdog/kill-watch.sh
LOG=${FAMILIA_KILL_LOG:-$HOME/.local/state/familia/kills.log}; mkdir -p "$(dirname "$LOG")"
{ journalctl -f -n0 -o short-iso & journalctl --user -f -n0 -o short-iso 2>/dev/null & wait; } |
awk -v out="$LOG" -v snap="$(dirname "$0")/mem-snapshot.sh" '
/memory: usage [0-9]+kB, limit/ { lim=$0; sub(/.*limit /,"",lim); sub(/,.*/,"",lim) }
/oom-kill:constraint=/ { c=$0; sub(/.*constraint=/,"",c); sub(/,.*/,"",c); m=$0; sub(/.*oom_memcg=/,"",m); sub(/,.*/,"",m) }
/Killed process/ { cause=(c=="CONSTRAINT_MEMCG")?"cgroup-memmax limit=" lim " memcg=" m:"kernel-oom"; print $1, cause, "|", $0 >> out; fflush(out); system(snap " >> " out); c=""; lim="" ; next }
/systemd-oomd.*[Kk]ill/ { print $1, "systemd-oomd |", $0 >> out; fflush(out); system(snap " >> " out); next }
/earlyoom.*(sending|[Kk]ill)/ { print $1, "earlyoom |", $0 >> out; fflush(out); system(snap " >> " out); next }
/familia-cap|PROCESS-DEATH|matrix-cap|watchdog.*(kill|restart)/ { print $1, "familia |", $0 >> out; fflush(out); system(snap " >> " out) }'
