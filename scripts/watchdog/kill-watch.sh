#!/bin/sh
# kill-watch.sh: follow kernel+system+user journals, log every process kill with its cause.
# Causes: cgroup-memmax (memcg limit; scope limit printed), kernel-oom (global), systemd-oomd,
# earlyoom, familia-cap (our launcher caps), watchdog. Output: ${FAMILIA_KILL_LOG:-~/.local/state/familia/kills.log}
# Kills of protected processes (connector grok-bot, dogfood loop, kill watcher; FAMILIA_PROTECTED regex)
# are tagged 'P0-PROTECTED' (#112) and also appended to protected-kills.log.
# Tests: KILL_WATCH_INPUT=fixture.log replays a recorded journal instead of following live.
# Read-only. Run: systemd-run --user --unit=familia-kill-watch scripts/watchdog/kill-watch.sh
LOG=${FAMILIA_KILL_LOG:-$HOME/.local/state/familia/kills.log}; mkdir -p "$(dirname "$LOG")"
PROT=${FAMILIA_PROTECTED:-grok-bot|appimage|kill-watch|loop\.sh|dispatch\.py|familia-dogfood|familia-kill-watch}
src() { if [ -n "${KILL_WATCH_INPUT:-}" ]; then cat "$KILL_WATCH_INPUT"; else
  journalctl -f -n0 -o short-iso & journalctl --user -f -n0 -o short-iso 2>/dev/null & wait; fi; }
SNAP=${KILL_WATCH_SNAP:-$(dirname "$0")/mem-snapshot.sh}
src | awk -v out="$LOG" -v pout="$(dirname "$LOG")/protected-kills.log" -v prot="$PROT" -v snap="$SNAP" '
function emit(cause) { p=($0 ~ ("(" prot ")")) ? "P0-PROTECTED " : ""; print $1, p cause, "|", $0 >> out; fflush(out)
  if (p != "") { print $1, "P0-PROTECTED", cause, "|", $0 >> pout; fflush(pout) }; system(snap " >> " out) }
/memory: usage [0-9]+kB, limit/ { lim=$0; sub(/.*limit /,"",lim); sub(/,.*/,"",lim) }
/oom-kill:constraint=/ { c=$0; sub(/.*constraint=/,"",c); sub(/,.*/,"",c); m=$0; sub(/.*oom_memcg=/,"",m); sub(/,.*/,"",m) }
/Killed process/ { cause=(c=="CONSTRAINT_MEMCG")?"cgroup-memmax limit=" lim " memcg=" m:"kernel-oom"; emit(cause); c=""; lim="" ; next }
/systemd-oomd.*[Kk]ill/ { emit("systemd-oomd"); next }
/earlyoom.*(sending|[Kk]ill)/ { emit("earlyoom"); next }
/familia-cap|PROCESS-DEATH|matrix-cap|watchdog.*(kill|restart)/ { emit("familia") }'
