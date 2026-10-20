#!/bin/sh
# One line: memory PSI, free -m, top-5 RSS processes (for kill-watch.sh).
printf '  snap psi=[%s] mem=[%s] top=[%s]\n' "$(tr '\n' ' ' </proc/pressure/memory)" "$(free -m | sed -n 2p)" "$(ps -eo rss=,pid=,comm= --sort=-rss | head -5 | tr '\n' ';')"
