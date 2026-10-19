#!/bin/sh
# Cheap, read-only power sample for registry records (docs/model-registry.md).
# Prints one JSON object. Never uses sudo. Run beside a benchmark another worker
# is already running; this script itself starts no load.
# Linux: RAPL package energy over N seconds (if readable). Android: battery
# current/voltage (instantaneous; only meaningful when unplugged).
case "${1:-}" in -h|--help)
  echo "Usage: sh scripts/power_probe.sh [SECONDS]   (default 5; RAPL is sampled over SECONDS)"
  echo "Prints one JSON power sample. Read-only, never uses sudo, starts no load."
  echo "Example: sh scripts/power_probe.sh 10"; exit 0 ;;
esac
N=${1:-5}
r=/sys/class/powercap/intel-rapl:0/energy_uj
if [ -r "$r" ]; then
  a=$(cat $r); sleep "$N"; b=$(cat $r)
  echo "{\"measured\": true, \"method\": \"rapl package-0 energy_uj over ${N}s\", \"watts\": $(awk "BEGIN{print ($b-$a)/1e6/$N}")}"; exit 0
fi
if command -v termux-battery-status >/dev/null 2>&1; then
  j=$(termux-battery-status); echo "{\"measured\": true, \"method\": \"termux-battery-status (instantaneous)\", \"raw\": $j}"; exit 0
fi
b=/sys/class/power_supply/battery
if [ -r $b/current_now ] && [ -r $b/voltage_now ]; then
  i=$(cat $b/current_now); v=$(cat $b/voltage_now)
  echo "{\"measured\": true, \"method\": \"sysfs battery current_now*voltage_now (instantaneous; sign/units vary by vendor)\", \"current_now\": $i, \"voltage_now\": $v}"; exit 0
fi
echo '{"measured": false, "watts": null, "method": "no readable RAPL or battery sensor without root"}'
