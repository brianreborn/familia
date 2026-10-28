#!/bin/sh
# deploy-probe.sh — one-command deploy of the pinned familia monitor probe (#71).
# Copies scripts/monitor/probe.py (and probe.ps1 when --windows) to
# ~/.local/share/familia/monitor-probe.{py,ps1} on each target host.
#
# Usage:
#   sh scripts/monitor/deploy-probe.sh [--dry-run] [--local] [HOST ...]
#   sh scripts/monitor/deploy-probe.sh --windows HOST
#
# HOST is an ssh alias (or user@host). With no HOST and --local, installs on this machine.
# With no args, reads ssh targets from ~/.config/familia/monitor.json hosts.*.ssh
# (never prints addresses from graph.yaml).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PROBE_PY="$ROOT/scripts/monitor/probe.py"
PROBE_PS1="$ROOT/scripts/monitor/probe.ps1"
REMOTE_DIR='.local/share/familia'
REMOTE_PY='monitor-probe.py'
REMOTE_PS1='monitor-probe.ps1'
CONFIG="${FAMILIA_MONITOR_CONFIG:-$HOME/.config/familia/monitor.json}"

DRY=0
LOCAL=0
WINDOWS=0
HOSTS=""

usage() {
  cat <<'U'
Usage: sh scripts/monitor/deploy-probe.sh [--dry-run] [--local] [--windows] [HOST ...]

Deploy the pinned monitor probe used with probe: "pinned" in monitor.json.
  --local     install under $HOME/.local/share/familia on this machine
  --windows   also/only copy probe.ps1 as monitor-probe.ps1 (OpenSSH Server hosts)
  --dry-run   print scp/cp commands without running them
  HOST        ssh alias or user@host (repeatable). If none and not --local,
              use hosts.*.ssh from ~/.config/familia/monitor.json
U
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --local) LOCAL=1 ;;
    --windows) WINDOWS=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) printf 'deploy-probe: unknown %s\n' "$1" >&2; usage >&2; exit 2 ;;
    *) HOSTS="$HOSTS $1" ;;
  esac
  shift
done

[ -f "$PROBE_PY" ] || { printf 'deploy-probe: missing %s\n' "$PROBE_PY" >&2; exit 1; }

run() {
  if [ "$DRY" = 1 ]; then
    printf '[dry-run]';
    printf ' %s' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

deploy_local() {
  dest_dir="$HOME/$REMOTE_DIR"
  run mkdir -p "$dest_dir"
  run cp -f "$PROBE_PY" "$dest_dir/$REMOTE_PY"
  if [ "$WINDOWS" = 1 ] || [ -f "$PROBE_PS1" ]; then
    if [ -f "$PROBE_PS1" ]; then
      run cp -f "$PROBE_PS1" "$dest_dir/$REMOTE_PS1"
    fi
  fi
  printf 'deploy-probe: local → %s/%s\n' "$dest_dir" "$REMOTE_PY"
}

deploy_ssh() {
  host=$1
  # mkdir then scp; BatchMode so we never hang on a password prompt
  run ssh -T -o BatchMode=yes -o ConnectTimeout=8 "$host" "mkdir -p \$HOME/$REMOTE_DIR"
  run scp -o BatchMode=yes -o ConnectTimeout=8 "$PROBE_PY" "$host:$REMOTE_DIR/$REMOTE_PY"
  if [ "$WINDOWS" = 1 ] && [ -f "$PROBE_PS1" ]; then
    run scp -o BatchMode=yes -o ConnectTimeout=8 "$PROBE_PS1" "$host:$REMOTE_DIR/$REMOTE_PS1"
  fi
  printf 'deploy-probe: %s → ~/%s/%s\n' "$host" "$REMOTE_DIR" "$REMOTE_PY"
}

# Collect hosts from config when none given
if [ -z "$(printf '%s' "$HOSTS" | tr -d ' ')" ] && [ "$LOCAL" != 1 ]; then
  if [ -f "$CONFIG" ]; then
    HOSTS=$(python3 - "$CONFIG" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
hosts = (cfg.get("hosts") or {})
for name, spec in hosts.items():
    if not isinstance(spec, dict):
        continue
    if spec.get("enabled") is False:
        continue
    if spec.get("local"):
        print("LOCAL")
        continue
    ssh = spec.get("ssh")
    if ssh:
        print(ssh)
PY
)
  fi
fi

did=0
if [ "$LOCAL" = 1 ]; then
  deploy_local
  did=1
fi

# shellcheck disable=SC2086
for h in $HOSTS; do
  [ -z "$h" ] && continue
  if [ "$h" = "LOCAL" ]; then
    deploy_local
    did=1
    continue
  fi
  deploy_ssh "$h"
  did=1
done

if [ "$did" = 0 ]; then
  printf 'deploy-probe: no targets. Pass HOST, --local, or configure hosts.*.ssh in %s\n' "$CONFIG" >&2
  exit 2
fi

printf 'deploy-probe: done. Set "probe": "pinned" in monitor.json for those hosts.\n'
printf 'See docs/monitoring.md (Hardened monitoring key).\n'
