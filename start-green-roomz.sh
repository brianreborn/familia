#!/bin/sh
# Guard stub for android_start.sh (issue #15). The real start-green-roomz.sh is
# produced/deployed from the green-roomz pin onto the device at /data/local/tmp.
# This repo-root copy exists so missing-file checks fail with a clear message
# instead of "No such file", and so local dry-runs do not pretend a room started.
set -eu
echo "start-green-roomz.sh: not deployed here." >&2
echo "start-green-roomz.sh: on Android, deploy green-roomz's launcher to /data/local/tmp/start-green-roomz.sh" >&2
echo "start-green-roomz.sh: pin is in pins.txt (green-roomz); see issue #15 and #21." >&2
exit 1
