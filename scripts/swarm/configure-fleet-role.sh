#!/bin/sh
set -eu
umask 077
usage(){ printf '%s\n' 'usage: configure-fleet-role.sh --role ROLE [--config PATH] [options]' 'roles: none thin-client model-server swarm-runner'; }
die(){ printf '%s\n' "configure-fleet-role: $*" >&2; exit 2; }
uint(){ printf '%s' "$1" | grep -Eq '^[0-9]+$'; }
num(){ printf '%s' "$1" | grep -Eq '^[0-9]+([.][0-9]+)?$'; }
tok(){ printf '%s' "$1" | grep -Eq '^[A-Za-z0-9._:-]+$'; }
role_ok(){ case "$1" in none|thin-client|model-server|swarm-runner) return 0;; *) return 1;; esac; }
mode_ok(){ case "$1" in live|triage|review|dry-run) return 0;; *) return 1;; esac; }
CONFIG=${SWARM_CONFIG_FILE:-$HOME/swarm/swarm-pull.conf}; ROLE=none; MODE=dry-run; RUNNER=; MODEL_URL=; MODEL_KEY_FILE=; UPSTREAM_HOST=; UPSTREAM_PORT=9941; THINK=1; PASSES=3; MAX_TOKENS=700; THINK_TOKENS=800; MIN_MEM_GIB=; MAX_LOAD1=; MAX_API_CALLS=80; API_WINDOW_SEC=3600; ARM=0; DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --config) [ $# -ge 2 ] || die '--config needs a path'; CONFIG=$2; shift 2;;
    --role) [ $# -ge 2 ] || die '--role needs a value'; ROLE=$2; shift 2;;
    --mode) [ $# -ge 2 ] || die '--mode needs a value'; MODE=$2; shift 2;;
    --runner) [ $# -ge 2 ] || die '--runner needs a value'; RUNNER=$2; shift 2;;
    --model-url) [ $# -ge 2 ] || die '--model-url needs a value'; MODEL_URL=$2; shift 2;;
    --model-key-file) [ $# -ge 2 ] || die '--model-key-file needs a path'; MODEL_KEY_FILE=$2; shift 2;;
    --upstream-host) [ $# -ge 2 ] || die '--upstream-host needs a value'; UPSTREAM_HOST=$2; shift 2;;
    --upstream-port) [ $# -ge 2 ] || die '--upstream-port needs a value'; UPSTREAM_PORT=$2; shift 2;;
    --think) [ $# -ge 2 ] || die '--think needs 0 or 1'; THINK=$2; shift 2;;
    --passes) [ $# -ge 2 ] || die '--passes needs an integer'; PASSES=$2; shift 2;;
    --max-tokens) [ $# -ge 2 ] || die '--max-tokens needs an integer'; MAX_TOKENS=$2; shift 2;;
    --think-tokens) [ $# -ge 2 ] || die '--think-tokens needs an integer'; THINK_TOKENS=$2; shift 2;;
    --min-mem-gib) [ $# -ge 2 ] || die '--min-mem-gib needs a number'; MIN_MEM_GIB=$2; shift 2;;
    --max-load1) [ $# -ge 2 ] || die '--max-load1 needs a number'; MAX_LOAD1=$2; shift 2;;
    --max-api-calls) [ $# -ge 2 ] || die '--max-api-calls needs an integer'; MAX_API_CALLS=$2; shift 2;;
    --api-window-sec) [ $# -ge 2 ] || die '--api-window-sec needs an integer'; API_WINDOW_SEC=$2; shift 2;;
    --arm) [ $# -ge 2 ] || die '--arm needs 0 or 1'; ARM=$2; shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "unknown option $1";;
  esac
done
role_ok "$ROLE" || die 'role must be none, thin-client, model-server, or swarm-runner'
mode_ok "$MODE" || die 'mode must be live, triage, review, or dry-run'
uint "$UPSTREAM_PORT" || die 'upstream port must be an integer'
uint "$PASSES" && [ "$PASSES" -ge 1 ] && [ "$PASSES" -le 5 ] || die 'passes must be 1..5'
uint "$MAX_TOKENS" && [ "$MAX_TOKENS" -ge 1 ] || die 'max tokens must be positive'
uint "$THINK_TOKENS" || die 'think tokens must be an integer'
uint "$MAX_API_CALLS" || die 'max API calls must be an integer'
uint "$API_WINDOW_SEC" || die 'API window must be an integer'
case "$THINK:$ARM" in 0:0|0:1|1:0|1:1) ;; *) die 'think and arm must be 0 or 1';; esac
[ -z "$RUNNER" ] || tok "$RUNNER" || die 'runner contains unsafe characters'
[ -z "$UPSTREAM_HOST" ] || tok "$UPSTREAM_HOST" || die 'upstream host contains unsafe characters'
[ -z "$MIN_MEM_GIB" ] || num "$MIN_MEM_GIB" || die 'min memory must be numeric'
[ -z "$MAX_LOAD1" ] || num "$MAX_LOAD1" || die 'max load must be numeric'
[ "$ROLE" != model-server ] || [ -n "$MODEL_KEY_FILE" ] || die 'model-server refuses to listen without --model-key-file'
[ -z "$MODEL_KEY_FILE" ] || case "$MODEL_KEY_FILE" in *[!A-Za-z0-9_./:@%+-]*) die 'model key path contains unsafe characters';; esac
case "$CONFIG" in /*) ;; *) die 'config path must be absolute';; esac
D=$(dirname -- "$CONFIG"); mkdir -p "$D"; [ ! -L "$CONFIG" ] || die 'refusing a symlink config'
T=$(mktemp "$D/.swarm-pull.conf.XXXXXX"); trap 'rm -f "$T"' EXIT HUP INT TERM
if [ -f "$CONFIG" ]; then
  cp -p "$CONFIG" "$CONFIG.bak"
  awk '!/^FAMILIA_FLEET_ROLE=|^SWARM_MODE=|^SWARM_RUNNER=|^SWARM_MODEL_URL=|^SWARM_MODEL_KEY_FILE=|^SWARM_UPSTREAM_HOST=|^SWARM_UPSTREAM_PORT=|^SWARM_MODEL_THINK=|^SWARM_MODEL_PASSES=|^SWARM_MODEL_MAX_TOKENS=|^SWARM_MODEL_THINK_TOKENS=|^SWARM_MIN_MEM_GIB=|^SWARM_MAX_LOAD1=|^SWARM_MAX_API_CALLS=|^SWARM_API_WINDOW_SEC=|^FAMILIA_FLEET_ARM=/' "$CONFIG" >"$T"
fi
{
  printf 'FAMILIA_FLEET_ROLE=%s\nSWARM_MODE=%s\n' "$ROLE" "$MODE"
  [ -z "$RUNNER" ] || printf 'SWARM_RUNNER=%s\n' "$RUNNER"
  [ -z "$MODEL_URL" ] || printf 'SWARM_MODEL_URL=%s\n' "$MODEL_URL"
  [ -z "$MODEL_KEY_FILE" ] || printf 'SWARM_MODEL_KEY_FILE=%s\n' "$MODEL_KEY_FILE"
  [ -z "$UPSTREAM_HOST" ] || printf 'SWARM_UPSTREAM_HOST=%s\n' "$UPSTREAM_HOST"
  printf 'SWARM_UPSTREAM_PORT=%s\nSWARM_MODEL_THINK=%s\nSWARM_MODEL_PASSES=%s\nSWARM_MODEL_MAX_TOKENS=%s\nSWARM_MODEL_THINK_TOKENS=%s\n' "$UPSTREAM_PORT" "$THINK" "$PASSES" "$MAX_TOKENS" "$THINK_TOKENS"
  [ -z "$MIN_MEM_GIB" ] || printf 'SWARM_MIN_MEM_GIB=%s\n' "$MIN_MEM_GIB"
  [ -z "$MAX_LOAD1" ] || printf 'SWARM_MAX_LOAD1=%s\n' "$MAX_LOAD1"
  printf 'SWARM_MAX_API_CALLS=%s\nSWARM_API_WINDOW_SEC=%s\nFAMILIA_FLEET_ARM=%s\n' "$MAX_API_CALLS" "$API_WINDOW_SEC" "$ARM"
} >>"$T"
chmod 600 "$T"
if [ "$DRY_RUN" = 1 ]; then if [ -f "$CONFIG" ]; then diff -u "$CONFIG" "$T" || :; else cat "$T"; fi; exit 0; fi
mv "$T" "$CONFIG"; trap - EXIT HUP INT TERM; printf 'wrote %s (backup %s.bak)\n' "$CONFIG" "$CONFIG"
