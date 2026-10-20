# display-watchdog.sh (software watchdog, centos10-bigram)

Installed as `/usr/local/sbin/familia-display-watchdog`, run by `/etc/cron.d/familia-display-watchdog`
every 5 min as root. Reboots after 3 consecutive strikes (~15 min) when the kernel log shows a GPU/DRM
hang or no `grok-bot` process runs for user green. 20 min grace after boot, at most 3 reboots a day,
log in `/var/log/familia-watchdog.log`. Disable: `touch /etc/familia-watchdog.off`.
A hardware watchdog (iTCO / systemd RuntimeWatchdogSec) comes later.
