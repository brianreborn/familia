#!/bin/sh
# Install familia-dogfood as a systemd user unit with Restart=always (#112; idempotent; no sudo).
# Runs loop.sh directly (comm "loop.sh") so earlyoom --avoid can match it.
# Never stops a loop that is already running outside the unit: enables only; starts once none runs.
set -e
D=$(cd "$(dirname "$0")" && pwd); U=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user; mkdir -p "$U"
cat > "$U/familia-dogfood.service" <<UNIT
[Unit]
Description=familia: autonomous dogfood fix loop
After=network-online.target
[Service]
ExecStart=$D/loop.sh
Restart=always
RestartSec=30
[Install]
WantedBy=default.target
UNIT
[ "${NO_SYSTEMCTL:-0}" = 1 ] && { echo "wrote $U/familia-dogfood.service"; exit 0; }
systemctl --user daemon-reload
systemctl --user enable familia-dogfood
if pgrep -f 'dogfood/loop.sh' >/dev/null && ! systemctl --user -q is-active familia-dogfood; then
  echo "loop already running outside the unit; enabled only (takes over on next login/restart)"
else systemctl --user start familia-dogfood; systemctl --user is-active familia-dogfood; fi
