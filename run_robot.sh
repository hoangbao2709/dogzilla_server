#!/bin/bash
# =============================================
# Script khoi dong Dogzilla server
# Tu dong kill tien trinh cu va luu PID de quan ly
# =============================================

set -u

DOG_PORT=9000
DOG_PID_FILE="/tmp/dogzilla_server.pid"
DOG_LOG_FILE="/tmp/dogzilla_server.log"

kill_pid_file() {
    local pid_file="$1"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo ">>> Killing old process PID $pid"
            kill "$pid"
            sleep 1
        fi
        rm -f "$pid_file"
    fi
}

cleanup() {
    echo
    echo ">>> Stopping Dogzilla server..."
    kill_pid_file "$DOG_PID_FILE"
    exit 0
}

trap cleanup INT TERM

echo ">>> Killing old processes..."
kill_pid_file "$DOG_PID_FILE"

echo ">>> Starting Dogzilla server..."
python3 -m dogzilla_server.app > "$DOG_LOG_FILE" 2>&1 &
DOG_PID=$!
echo "$DOG_PID" > "$DOG_PID_FILE"
sleep 3

echo
echo "================ Robot is running ================"
echo "Dogzilla server PID: $DOG_PID"
echo "Server port:         $DOG_PORT"
echo "Server log:          $DOG_LOG_FILE"
echo "Press CTRL + C to stop."
echo "=================================================="

while true; do
    sleep 1
done
