#!/bin/sh
# familia-monitor: SSH-based fleet console. See docs/monitoring.md or --help.
here=$(cd "$(dirname "$0")" && pwd)
exec python3 "$here/monitor.py" "$@"
