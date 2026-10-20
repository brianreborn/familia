#!/bin/sh
# linux-memory.sh apply|revert|status  -- relax OS memory killers so models can use most of RAM.
# Idempotent; backups in /var/lib/familia-tune. Run with: sudo sh scripts/tune/linux-memory.sh apply
#  - systemd-oomd: user@.service ManagedOOMMemoryPressureLimit=90% (default 50%)
#  - earlyoom (if installed): -m 3,2 -s 5,3 (keeps llama-* prefer list)
#  - sysctl: vm.swappiness=60 (zram-friendly), vm.min_free_kbytes=131072, vm.overcommit_memory=0
#  - zram (ZRAM=1, needs zram-generator): zram0 = 50% RAM, zstd
set -e
B=/var/lib/familia-tune; OD=/etc/systemd/system/user@.service.d/90-familia-oomd.conf
SC=/etc/sysctl.d/90-familia-memory.conf; ZR=/etc/systemd/zram-generator.conf.d/90-familia.conf; EO=/etc/default/earlyoom
case "$1" in
apply)
  [ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
  mkdir -p "$B" "$(dirname "$OD")"
  printf '[Service]\nManagedOOMMemoryPressure=kill\nManagedOOMMemoryPressureLimit=90%%\n' > "$OD"
  printf 'vm.swappiness=60\nvm.min_free_kbytes=131072\nvm.overcommit_memory=0\n' > "$SC"; sysctl -q -p "$SC"
  if [ -f "$EO" ]; then [ -f "$B/earlyoom" ] || cp -p "$EO" "$B/earlyoom"
    sed -i 's/-m [0-9,]* -s [0-9,]*/-m 3,2 -s 5,3/' "$EO"; systemctl try-restart earlyoom; fi
  if [ "${ZRAM:-0}" = 1 ] && [ -d /usr/lib/systemd/zram-generator.conf.d -o -x /usr/lib/systemd/system-generators/zram-generator ]; then
    mkdir -p "$(dirname "$ZR")"; printf '[zram0]\nzram-size = ram / 2\ncompression-algorithm = zstd\nswap-priority = 100\n' > "$ZR"
    systemctl daemon-reload; systemctl restart systemd-zram-setup@zram0 || true; fi
  systemctl daemon-reload; systemctl try-restart systemd-oomd; echo applied;;
revert)
  rm -f "$OD" "$SC" "$ZR"; [ -f "$B/earlyoom" ] && cp -p "$B/earlyoom" "$EO" && systemctl try-restart earlyoom
  systemctl daemon-reload; systemctl try-restart systemd-oomd; echo "reverted (sysctls reset at reboot)";;
*) systemctl show user@1000.service -p ManagedOOMMemoryPressureLimit; sysctl vm.swappiness vm.min_free_kbytes; swapon --show; grep -s ARGS "$EO";;
esac
