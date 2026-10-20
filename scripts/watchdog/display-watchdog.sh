#!/bin/sh
# familia display watchdog: reboot if significantly stuck. Disable: touch /etc/familia-watchdog.off
S=/var/lib/familia-watchdog; L=/var/log/familia-watchdog.log; mkdir -p $S
[ -e /etc/familia-watchdog.off ] && exit 0
up=$(cut -d. -f1 /proc/uptime); [ "$up" -lt 1200 ] && exit 0
bad=""
journalctl -k --since -10min -q 2>/dev/null | grep -Eiq 'gpu lockup|nouveau.*(fifo|timeout|fault)|NVRM: Xid|drm.*(hang|timed out)' && bad="gpu-kernel-error"
pgrep -u green -f 'grok-bot' >/dev/null || bad="${bad:+$bad,}grokbot-missing"
if [ -z "$bad" ]; then rm -f $S/strikes; exit 0; fi
n=$(( $(cat $S/strikes 2>/dev/null || echo 0) + 1 )); echo $n > $S/strikes
echo "$(date -Is) strike $n: $bad" >> $L
[ "$n" -lt 3 ] && exit 0
today=$(date +%F); c=$(grep -c "^$today.*REBOOT" $L 2>/dev/null)
[ "$c" -ge 3 ] && { echo "$(date -Is) limit reached, no reboot" >> $L; exit 0; }
echo "$(date -Is) REBOOT ($bad)" >> $L; rm -f $S/strikes; sync; systemctl reboot
