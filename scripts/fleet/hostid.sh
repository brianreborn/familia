#!/bin/sh
# familia fleet host ID (POSIX sh; Linux, Termux/Android, FreeBSD, macOS, Git-Bash).
#
#   hostid.sh [--label NAME] [--json] [--anchor-type]
#
# Prints the canonical fleet host ID:  <label-slug>-<fp8>
#   fp8 = first 8 hex of sha256("familia-hostid-v1|<anchor_type>|<anchor>")
# The anchor is a stable hardware/OS identifier that is the same over every
# transport (USB, Wi-Fi, ethernet). The raw anchor is NEVER printed; only the
# salted hash prefix leaves this script. Read-only: writes nothing.
#
# Anchor order (first non-empty wins); keep in sync with scripts/fleet/hostid.py:
#   android-serial  getprop ro.serialno / ro.boot.serialno (== adb serial)
#   soc-serial      /sys/devices/soc0/serial_number (Android SoC serial; Termux-readable on Snapdragon)
#   android-id      settings get secure android_id
#   machine-id      /etc/machine-id, /var/lib/dbus/machine-id
#   hostuuid        FreeBSD sysctl kern.hostuuid, /etc/hostid
#   platform-uuid   macOS IOPlatformUUID
#   machine-guid    Windows MachineGuid (Git-Bash/MSYS via reg.exe)
#   state-uuid      $XDG_STATE_HOME/familia/host-uuid (created only by hostid.py --init)
#   mac             first physical NIC MAC (fallback only; differs per transport on phones)
#   hostname        no anchor found: weak ID from the label (flagged in --json)
LABEL=""; JSON=0; ATYPE_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --label) LABEL=$2; shift 2 ;;
    --label=*) LABEL=${1#--label=}; shift ;;
    --json) JSON=1; shift ;;
    --anchor-type) ATYPE_ONLY=1; shift ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    *) echo "hostid.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

clean() { tr -d ' \t\r\n' | tr 'A-Z' 'a-z'; }
bad() { case "$1" in ""|unknown|0|00000000|0123456789abcdef|null|*not*found*|*00000000-0000-0000-0000-000000000000*) return 0 ;; esac; return 1; }

AT=""; AV=""
try() { v=$(printf '%s' "$2" | clean); if [ -z "$AT" ] && ! bad "$v"; then AT=$1; AV=$v; fi; }

if command -v getprop >/dev/null 2>&1; then
  try android-serial "$(getprop ro.serialno 2>/dev/null)"
  try android-serial "$(getprop ro.boot.serialno 2>/dev/null)"
  [ -z "$AT" ] && [ -r /sys/devices/soc0/serial_number ] && try soc-serial "$(head -c 64 /sys/devices/soc0/serial_number 2>/dev/null)"
  if [ -z "$AT" ] && command -v settings >/dev/null 2>&1; then
    try android-id "$(settings get secure android_id 2>/dev/null)"
  fi
fi
for f in /etc/machine-id /var/lib/dbus/machine-id; do
  [ -z "$AT" ] && [ -r "$f" ] && try machine-id "$(head -c 64 "$f" 2>/dev/null)"
done
if [ -z "$AT" ] && command -v sysctl >/dev/null 2>&1; then
  try hostuuid "$(sysctl -n kern.hostuuid 2>/dev/null)"
fi
[ -z "$AT" ] && [ -r /etc/hostid ] && try hostuuid "$(head -c 64 /etc/hostid 2>/dev/null)"
if [ -z "$AT" ] && command -v ioreg >/dev/null 2>&1; then
  try platform-uuid "$(ioreg -rd1 -c IOPlatformExpertDevice 2>/dev/null | sed -n 's/.*"IOPlatformUUID" = "\(.*\)".*/\1/p')"
fi
if [ -z "$AT" ] && command -v reg >/dev/null 2>&1; then
  try machine-guid "$(reg query 'HKLM\SOFTWARE\Microsoft\Cryptography' //v MachineGuid 2>/dev/null | sed -n 's/.*MachineGuid[^0-9A-Fa-f]*\([0-9A-Fa-f-]*\).*/\1/p')"
fi
SD=${XDG_STATE_HOME:-$HOME/.local/state}/familia
[ -z "$AT" ] && [ -r "$SD/host-uuid" ] && try state-uuid "$(head -c 64 "$SD/host-uuid")"
if [ -z "$AT" ] && [ -d /sys/class/net ]; then
  for n in $(ls /sys/class/net 2>/dev/null | sort); do
    case "$n" in lo|docker*|veth*|br*|virbr*|tun*|tap*|wg*|rndis*|usb*|vnet*|dummy*|bond*|tailscale*|zt*) continue ;; esac
    [ -e "/sys/class/net/$n/device" ] || continue
    try mac "$(cat "/sys/class/net/$n/address" 2>/dev/null)"
    [ -n "$AT" ] && break
  done
fi

# label: --label, $FAMILIA_HOST_LABEL, hostname pin, uname -n (localhost* -> host)
[ -n "$LABEL" ] || LABEL=${FAMILIA_HOST_LABEL:-}
[ -n "$LABEL" ] || { [ -r "$SD/hostname" ] && LABEL=$(head -1 "$SD/hostname"); }
[ -n "$LABEL" ] || LABEL=$(uname -n 2>/dev/null)
LABEL=${LABEL%%.*}
SLUG=$(printf '%s' "$LABEL" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9-\n' '-' | tr -d '\n' | sed 's/--*/-/g; s/^-//; s/-$//' | cut -c1-24)
case "$SLUG" in ""|localhost) SLUG=host ;; esac
if [ -z "$AT" ]; then AT=hostname; AV=$SLUG; fi

sha() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256
  elif command -v sha256 >/dev/null 2>&1; then sha256 -q
  else openssl dgst -sha256 -r; fi
}
FP=$(printf 'familia-hostid-v1|%s|%s' "$AT" "$AV" | sha | cut -c1-8)
AV=""
if [ "$ATYPE_ONLY" = 1 ]; then echo "$AT"
elif [ "$JSON" = 1 ]; then
  W=false; [ "$AT" = hostname ] || [ "$AT" = mac ] && W=true
  printf '{"host_id": "%s-%s", "label": "%s", "fingerprint": "%s", "anchor_type": "%s", "weak": %s}\n' "$SLUG" "$FP" "$SLUG" "$FP" "$AT" "$W"
else echo "$SLUG-$FP"; fi
