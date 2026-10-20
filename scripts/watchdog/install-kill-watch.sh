#!/bin/sh
# Install familia-kill-watch as a persistent, enabled systemd user unit (idempotent; no sudo).
set -e
D=$(cd "$(dirname "$0")" && pwd); U=$HOME/.config/systemd/user; mkdir -p "$U"
cat > "$U/familia-kill-watch.service" <<UNIT
[Unit]
Description=familia: log every process kill with cause
[Service]
ExecStart=$D/kill-watch.sh
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
UNIT
systemctl --user stop familia-kill-watch 2>/dev/null || true
systemctl --user reset-failed familia-kill-watch 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now familia-kill-watch
systemctl --user is-active familia-kill-watch
