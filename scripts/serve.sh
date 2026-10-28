#!/bin/sh
# Launch a graph node's llama-server: sh scripts/serve.sh <node> [extra llama-server args]
# The arguments come from `validate_graph.py --args <node>`, which includes every REQUIRED and
# RECOMMENDED model parameter (#51, docs/model-params.md) and exits 1 when one cannot be met;
# serve.sh then refuses to start. An embedding node must carry --embeddings and --pooling.
# The licenses of the graph selection must be accepted first (scripts/licenses.py gate).
# Memory cap (docs/ram-safety.md): FAMILIA_MEMCAP=1 wraps the server in a
# `systemd-run --user --scope` with a headroom MemoryMax (swap allowed) and sets oom_score_adj 800,
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
if [ -n "${FAMILIA_HOST:-}" ]; then
  # The host name comes from graph selection, not arbitrary shell text.
  case "$FAMILIA_HOST" in *[!A-Za-z0-9._-]*)
    say "invalid FAMILIA_HOST=$FAMILIA_HOST"
    exit 2
    ;;
  esac
  if ! args="$(python3 "$here/scripts/validate_graph.py" --graph "$here/graph.yaml" --host "$FAMILIA_HOST" --args "$node")"; then
    say "validate_graph.py --args $node failed for host $FAMILIA_HOST (see above); not starting"
    exit 1
  fi
else
  if ! args="$(python3 "$here/scripts/validate_graph.py" --graph "$here/graph.yaml" --args "$node")"; then
    say "validate_graph.py --args $node failed (see above); not starting"
    exit 1
  fi
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
  _fh="${FAMILIA_HOST:-}"
  [ -n "$_fh" ] || _fh="$(python3 "$here/scripts/hostname_pin.py" resolve 2>/dev/null || true)"
  [ -n "$_fh" ] || _fh="$(hostname 2>/dev/null | cut -d. -f1)"
  case "$_fh" in miryam*) FAMILIA_MEMCAP=1 ;; *) FAMILIA_MEMCAP=0 ;; esac
fi
# The model file must exist: never start a node without its model.
model="$(printf '%s\n' "$args" | sed -n -E 's/.*[[:space:]]-m[[:space:]]+([^[:space:]]+).*/\1/p')"
if [ -n "$model" ] && [ ! -f "$model" ]; then
  say "model file $model of node $node not found; not starting"
  exit 1
fi
# The runtime binary must exist too: a pinned runtime that was never fetched used to end
# in a bare "not found" and rc 127 (#84).
bin="${args%% *}"
case "$bin" in */*)
  if [ ! -x "$bin" ]; then
    say "runtime $bin of node $node is missing or not executable; fetch the pinned runtime (sh scripts/configure.sh, or scripts/sync_pins.py) and check runtimes.*.bin in graph.yaml; not starting"
    exit 1
  fi ;;
esac
# Race TOCTOU: capture Platform fingerprint after bin check; re-assert immediately before
# exec/spawn (swap window between PolicyGate/first refuse and screen attach). Soft skip
# when scripts/refuse_soname_skew.py is not present yet.
_race_fp_capture=""
_race_fp_assert() {
  [ -n "${_race_fp_capture}" ] || return 0
  [ -f "$here/scripts/miryam_perf_seatbelts.py" ] || return 0
  case "$bin" in */*) ;; *) return 0 ;; esac
  _race_out="$(printf '%s\n' "$_race_fp_capture" | python3 "$here/scripts/miryam_perf_seatbelts.py" assert-stable --bin "$bin" --capture-json -)" || {
    say "soname_fingerprint_drift: runtime $bin changed between check and exec (Race TOCTOU); not starting $node"
    printf '%s\n' "${_race_out:-}" >&2
    exit 1
  }
  # CLI prints JSON and exits 1 on refuse; also refuse if ok:false slipped through.
  case "$_race_out" in *"\"ok\": false"*|*"\"ok\":false"*)
    say "soname_fingerprint_drift: runtime $bin refused late fingerprint check; not starting $node"
    printf '%s\n' "$_race_out" >&2
    exit 1
    ;;
  esac
  unset _race_out
}
if [ -f "$here/scripts/miryam_perf_seatbelts.py" ]; then
  case "$bin" in */*)
    _race_fp_capture="$(python3 "$here/scripts/miryam_perf_seatbelts.py" capture --bin "$bin" 2>/dev/null || true)"
    if ! python3 "$here/scripts/miryam_perf_seatbelts.py" check-skew --bin "$bin" >/dev/null; then
      say "check_soname_skew refused runtime $bin; not starting $node"
      exit 1
    fi
    ;;
  esac
fi
# Launch guard: refuse params bench_guard flags (removed flags, ctx > train, encoder ubatch,
# quantized V without FA, GPU layers on a legacy GPU). FAMILIA_GUARD=0 skips it.
if [ "${FAMILIA_GUARD:-1}" != 0 ] && [ ! -f "$here/scripts/bench_guard.py" ]; then
  say "warning: scripts/bench_guard.py missing; launch guard skipped"
elif [ "${FAMILIA_GUARD:-1}" != 0 ]; then
  # shellcheck disable=SC2086
  if ! python3 "$here/scripts/bench_guard.py" check -- ${args#* } "$@"; then
    gr=$?
    say "launch guard refused node $node (see familia-guard lines above); fix the params in graph.yaml; not starting"
    exit "$gr"
  fi
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
# #83: if the binary path still looks like a Vulkan pack, also pass --no-op-offload (child argv only).
case " $args " in *" -ngl 0 "*)
  [ -n "${GGML_VK_VISIBLE_DEVICES+set}" ] || export GGML_VK_VISIBLE_DEVICES=
  case "$bin" in *vulkan*|*Vulkan*)
    case " $args " in *" --no-op-offload "*) ;; *) args="$args --no-op-offload" ;; esac
    ;;
  esac
  ;;
esac
# shellcheck disable=SC2086
if [ "$FAMILIA_MEMCAP" = 1 ] && command -v systemd-run >/dev/null 2>&1; then
  # Hard cap = admission reservation, swap allowed;
  # no fixed 2600M / MemorySwapMax=0 any more (premature kills, P0 #95).
  # Cap = this launch's own admission reservation (estimated peak), never global headroom:
  # independent headroom caps overcommit (27 GiB of caps on a 23 GiB box, #95).
  # mmap+swap_budget: admit KV+cache+working-set, not full GGUF (docs/vvram-ssd/LAYER.md).
  if [ -z "${FAMILIA_MEMMAX:-}" ]; then
    FAMILIA_MEMMAX="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]+"/scripts"); import validate_graph as vg; g=vg.load(sys.argv[1]+"/graph.yaml"); print("%dM" % vg.admit_peak_mib(g, sys.argv[2]))' "$here" "$node" 2>/dev/null || python3 -c 'import os, sys; print("%dM" % (os.path.getsize(sys.argv[1]) / 2**20 * 1.15 + 768))' "$model" 2>/dev/null || echo 4096M)"
  fi
  # Fleet-wide admission: reserve the cap before launch so concurrent launches compose (#95).
  # The reservation is keyed to this shell's pid, which exec keeps for the server.
  if ! python3 "$here/scripts/launch_status.py" admit --mib "${FAMILIA_MEMMAX%M}" --pid $$ --tag "$node"; then
    python3 "$here/scripts/launch_status.py" emit LF_OOM_CAP --engine serve --model "$model" --evidence "admission refused for node $node"
    exit 69
  fi
  _race_fp_assert
  exec systemd-run --user --scope --quiet --unit="familia-$node-$$" \
    ${FAMILIA_MEMHIGH:+-p MemoryHigh="$FAMILIA_MEMHIGH"} -p MemoryMax="$FAMILIA_MEMMAX" \
    -- sh -c 'echo ${FAMILIA_OOM_ADJ:-800} > /proc/self/oom_score_adj; exec "$@"' sh $args "$@"
fi
ngl="$(printf '%s\n' "$args" | sed -n -E 's/.*[[:space:]]-ngl[[:space:]]+([0-9]+).*/\1/p')"
logdir="${FAMILIA_LOG_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/familia/logs}"
mkdir -p "$logdir"
log="$logdir/serve-$node.log"
: > "$log"
rc=0
_race_fp_assert
# shellcheck disable=SC2086
$args --log-file "$log" "$@" || rc=$?
[ "$rc" -eq 0 ] && exit 0
# Retry on the CPU only for a Vulkan failure of a GPU launch that was not stopped by a signal.
if [ "${ngl:-0}" -gt 0 ] && [ "$rc" -lt 128 ] && \
   grep -q -i -E -e 'ggml_vulkan: *(error|fail)|vk::[A-Za-z]*error|VK_ERROR_|failed to (initiali[sz]e|create).*vulkan|vulkan.*unsupported device' "$log"; then
  say "Vulkan launch failed (exit $rc, $log); retrying on the CPU with -ngl 0 and Vulkan hidden"
  export GGML_VK_VISIBLE_DEVICES=
  safe_args="$(printf '%s\n' "$args" | sed -E 's/(^|[[:space:]])-ngl[[:space:]]+[0-9]+/\1-ngl 0/')"
  # #83: Vulkan packs still op-offload at -ngl 0; disable op offload on the CPU retry.
  case " $safe_args " in *" --no-op-offload "*) ;; *) safe_args="$safe_args --no-op-offload" ;; esac
  _race_fp_assert
  # shellcheck disable=SC2086
  exec $safe_args --log-file "$log.cpu" "$@"
fi
exit "$rc"
