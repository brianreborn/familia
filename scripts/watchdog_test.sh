#!/bin/sh
# watchdog_test.sh: Run a test with a timeout watchdog.
# Usage: sh scripts/watchdog_test.sh <command> [<args...>] [WATCHDOG_SECONDS]
# If WATCHDOG_SECONDS not set, defaults to 300 (5 minutes).
# On timeout, kills the process and exits with code 124.
# On success, exits with the process's exit code.

CMD="$1"
shift
WATCHDOG_SECONDS="${1:-300}"
shift

# Start the command
$CMD "$@" &
PID=$!

# Wait for the process with a timeout
wait $PID
EXIT_CODE=$?

if [ $? -eq 124 ]; then
    # Timeout exceeded — kill the process
    kill -9 $PID 2>/dev/null
    echo "WATCHDOG: test timed out after ${WATCHDOG_SECONDS}s (PID=$PID); killing and exiting 124"
    exit 124
fi

exit $EXIT_CODE
