#!/bin/sh
# Launch a graph node's llama-server: sh scripts/serve.sh <node> [extra llama-server args]
# Memory cap (docs/ram-safety.md): FAMILIA_MEMCAP=1 wraps the server in a
# `systemd-run --user --scope` with MemoryHigh/MemoryMax and sets oom_score_adj 800,
# so on memory pressure the model dies, not the desktop. Default: on for miryam, off elsewhere.
# Override the limits with FAMILIA_MEMHIGH / FAMILIA_MEMMAX (systemd sizes, e.g. 2200M).
set -eu
# Simple logger for serve.sh
say() { printf '%s\n' "familia-serve: $*"; }
node="${1:?usage: serve.sh <node> [args]}"; shift
here="$(cd "$(dirname "$0")/.." && pwd)"
args="$(python3 "$here/scripts/validate_graph.py" --graph "$here/graph.yaml" --args "$node")"
if [ -z "${FAMILIA_MEMCAP:-}" ]; then
  case "$(hostname)" in miryam*) FAMILIA_MEMCAP=1 ;; *) FAMILIA_MEMCAP=0 ;; esac
fi
# Vulkan builds allocate ~1.83 GB of host buffers in shmem even with -ngl 0, counted
# against the memcap scope (LESSONS-LEARNED L-vkshm). With no GPU layers, hide Vulkan unless set.
case " $args " in *" -ngl 0 "*)
  [ -n "${GGML_VK_VISIBLE_DEVICES+set}" ] || export GGML_VK_VISIBLE_DEVICES= ;;
esac
# Embed model detection – skip if missing
if echo "$args" | grep -q "--embed"; then
  EMBED_MODEL=$(echo "$args" | sed -n -E 's/.*--embed[[:space:]]+([^[:space:]]+).*/\1/p')
  if [ ! -f "$EMBED_MODEL" ]; then
    say "Embed model $EMBED_MODEL not found – disabling embed route"
    args=$(echo "$args" | sed -E 's/[[:space:]]+--embed[[:space:]]+[^[:space:]]+//')
  fi
fi
# shellcheck disable=SC2086
if [ "$FAMILIA_MEMCAP" = 1 ] && command -v systemd-run >/dev/null 2>&1; then
  exec systemd-run --user --scope --quiet --unit="familia-$node-$$" \
    -p MemoryHigh="${FAMILIA_MEMHIGH:-2200M}" -p MemoryMax="${FAMILIA_MEMMAX:-2600M}" -p MemorySwapMax=0 \
    -- sh -c 'echo 800 > /proc/self/oom_score_adj; exec "$@"' sh $args "$@"
fi
# Try to launch with Vulkan; if it fails, fall back to CPU
run_with_fallback() {
  # First attempt (original args)
  if $args "$@"; then
    return 0
  fi
  # Detect Vulkan‑related failure (common exit code 1 with error output containing "Vulkan" or "unsupported device")
  if dmesg | grep -i -E "vulkan|unsupported device" >/dev/null 2>&1 || true; then
    say "Vulkan launch failed – retrying without Vulkan"
    # Unset Vulkan device env and force CPU path (-ngl 0)
    unset GGML_VK_VISIBLE_DEVICES
    # Replace any "-ngl <num>" with "-ngl 0" in the args string
    safe_args=$(echo "$args" | sed -E 's/-ngl[[:space:]]+[0-9]+/-ngl 0/')
    $safe_args "$@"
    return $?
  fi
  # If not a Vulkan issue, just propagate the original failure
  return 1
}
run_with_fallback