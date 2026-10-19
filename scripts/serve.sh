#!/bin/sh
# Launch a graph node's llama-server: sh scripts/serve.sh <node> [extra llama-server args]
# The arguments come from `validate_graph.py --args <node>`, which includes every REQUIRED and
# RECOMMENDED model parameter (#51, docs/model-params.md) and exits 1 when one cannot be met;
# serve.sh then refuses to start. An embedding node must carry --embeddings and --pooling.
# The licenses of the graph selection must be accepted first (scripts/licenses.py gate).
# Memory cap (docs/ram-safety.md): FAMILIA_MEMCAP=1 wraps the server in a
# `systemd-run --user --scope` with MemoryHigh/MemoryMax and sets oom_score_adj 800,
# so on memory pressure the model dies, not the desktop. Default: on for miryam, off elsewhere.
# Override the limits with FAMILIA_MEMHIGH / FAMILIA_MEMMAX (systemd sizes, e.g. 2200M).
# Without the memory cap, a launch with GPU layers (-ngl > 0) that fails with a Vulkan error
# (in its --log-file) is retried once on the CPU (-ngl 0) with Vulkan hidden
# (GGML_VK_VISIBLE_DEVICES=, LESSONS-LEARNED L-vkshm). Any other failure is returned as is.
set -eu
say() { printf '%s\n' "familia-serve: $*" >&2; }
case "${1:-}" in
  ""|-h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; [ -n "${1:-}" ] && exit 0; exit 2 ;;
esac
node="$1"; shift
here="$(cd "$(dirname "$0")/.." && pwd)"
if ! args="$(python3 "$here/scripts/validate_graph.py" --graph "$here/graph.yaml" --args "$node")"; then
  say "validate_graph.py --args $node failed (see above); not starting"
  exit 1
fi
# Licenses first (docs/licenses.md): the graph selection's licenses must be accepted before any
# model starts. scripts/licenses.py gate asks on a terminal; FAMILIA_ACCEPT_LICENSES=yes accepts.
if [ ! -f "$here/scripts/licenses.py" ]; then
  say "scripts/licenses.py not found; licenses must be accepted before a model starts; not starting"
  exit 1
fi
if ! python3 "$here/scripts/licenses.py" gate --graph "$here/graph.yaml"; then
  say "licenses not accepted (scripts/licenses.py review, or FAMILIA_ACCEPT_LICENSES=yes); not starting $node"
  exit 1
fi
# Pinned parts first, all together (REQUIREMENTS.md R-sync; scripts/sync_pins.py).
if [ -f "$here/scripts/sync_pins.py" ]; then
  python3 "$here/scripts/sync_pins.py" --auto || { rc=$?; echo "familia-serve: the pinned parts could not be synced (see above); stopped" >&2; exit $rc; }
  FAMILIA_SYNC_DONE="$here"; export FAMILIA_SYNC_DONE
fi
if [ -z "${FAMILIA_MEMCAP:-}" ]; then
  case "$(hostname)" in miryam*) FAMILIA_MEMCAP=1 ;; *) FAMILIA_MEMCAP=0 ;; esac
fi
# The model file must exist: never start a node without its model.
model="$(printf '%s\n' "$args" | sed -n -E 's/.*[[:space:]]-m[[:space:]]+([^[:space:]]+).*/\1/p')"
if [ -n "$model" ] && [ ! -f "$model" ]; then
  say "model file $model of node $node not found; not starting"
  exit 1
fi
# Embedders need --embeddings and --pooling (REQUIRED, #51). grep -e: the pattern starts with "-".
if printf '%s\n' "$args" | grep -q -E -e '(^|[[:space:]])--embeddings?([[:space:]]|$)'; then
  if ! printf '%s\n' "$args" | grep -q -E -e '(^|[[:space:]])--pooling[[:space:]]'; then
    say "node $node serves embeddings without --pooling (REQUIRED by the model card); not starting"
    exit 1
  fi
fi
# Vulkan builds allocate ~1.83 GB of host buffers in shmem even with -ngl 0, counted
# against the memcap scope (LESSONS-LEARNED L-vkshm). With no GPU layers, hide Vulkan unless set.
case " $args " in *" -ngl 0 "*)
  [ -n "${GGML_VK_VISIBLE_DEVICES+set}" ] || export GGML_VK_VISIBLE_DEVICES= ;;
esac
# shellcheck disable=SC2086
if [ "$FAMILIA_MEMCAP" = 1 ] && command -v systemd-run >/dev/null 2>&1; then
  exec systemd-run --user --scope --quiet --unit="familia-$node-$$" \
    -p MemoryHigh="${FAMILIA_MEMHIGH:-2200M}" -p MemoryMax="${FAMILIA_MEMMAX:-2600M}" -p MemorySwapMax=0 \
    -- sh -c 'echo 800 > /proc/self/oom_score_adj; exec "$@"' sh $args "$@"
fi
ngl="$(printf '%s\n' "$args" | sed -n -E 's/.*[[:space:]]-ngl[[:space:]]+([0-9]+).*/\1/p')"
logdir="${FAMILIA_LOG_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/familia/logs}"
mkdir -p "$logdir"
log="$logdir/serve-$node.log"
: > "$log"
rc=0
# shellcheck disable=SC2086
$args --log-file "$log" "$@" || rc=$?
[ "$rc" -eq 0 ] && exit 0
# Retry on the CPU only for a Vulkan failure of a GPU launch that was not stopped by a signal.
if [ "${ngl:-0}" -gt 0 ] && [ "$rc" -lt 128 ] && \
   grep -q -i -E -e 'ggml_vulkan: *(error|fail)|vk::[A-Za-z]*error|VK_ERROR_|failed to (initiali[sz]e|create).*vulkan|vulkan.*unsupported device' "$log"; then
  say "Vulkan launch failed (exit $rc, $log); retrying on the CPU with -ngl 0 and Vulkan hidden"
  export GGML_VK_VISIBLE_DEVICES=
  safe_args="$(printf '%s\n' "$args" | sed -E 's/(^|[[:space:]])-ngl[[:space:]]+[0-9]+/\1-ngl 0/')"
  # shellcheck disable=SC2086
  exec $safe_args --log-file "$log.cpu" "$@"
fi
exit "$rc"
