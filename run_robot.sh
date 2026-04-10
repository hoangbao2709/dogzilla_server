#!/bin/bash
# =============================================
# Script kh?i �?ng Dogzilla + Cloudflare tunnel
# T? �?ng kill c�c ti?n tr?nh c?
# L�u PID �? qu?n l?
# =============================================

set -u  # B�o l?i n?u bi?n ch�a ��?c khai b�o

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DOG_PORT=9000
NGINX_PORT=9002
LOG_CF="/tmp/cloudflared.log"
DOG_PID_FILE="/tmp/dogzilla_server.pid"
CF_PID_FILE="/tmp/cloudflared.pid"

# ========================
# H�m kill ti?n tr?nh n?u c?n ch?y
# ========================
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

# ========================
# Cleanup khi Ctrl+C
# ========================
cleanup() {
    echo
    echo ">>> Stopping Dogzilla and Cloudflare..."
    kill_pid_file "$DOG_PID_FILE"
    kill_pid_file "$CF_PID_FILE"
    exit 0
}

trap cleanup INT TERM

# ========================
# Kill c�c ti?n tr?nh c?
# ========================
echo ">>> Killing old processes..."
kill_pid_file "$DOG_PID_FILE"
kill_pid_file "$CF_PID_FILE"

# ========================
# Start Dogzilla server
# ========================
echo ">>> Starting Dogzilla server..."
python3 -m dogzilla_server.app > /tmp/dogzilla_server.log 2>&1 &
DOG_PID=$!
echo "$DOG_PID" > "$DOG_PID_FILE"
sleep 3

# ========================
# Start Cloudflare tunnel
# ========================
echo ">>> Starting Cloudflare tunnel (nginx:${NGINX_PORT})..."
rm -f "$LOG_CF"
cloudflared tunnel --url "http://127.0.0.1:${NGINX_PORT}" --no-autoupdate > "$LOG_CF" 2>&1 &
CF_PID=$!
echo "$CF_PID" > "$CF_PID_FILE"

# ========================
# T?m Cloudflare URL (max 60s)
# ========================
CF_URL=""
for i in $(seq 1 60); do
    if [ -f "$LOG_CF" ]; then
        CF_URL=$(grep -Eo 'https://[^ ]*trycloudflare\.com[^ ]*' "$LOG_CF" 2>/dev/null | head -n1 || true)
        if [ -n "$CF_URL" ]; then
            break
        fi
    fi
    sleep 1
done

if [ -n "$CF_URL" ]; then
    echo ">>> Cloudflare URL detected: $CF_URL"
    echo ">>> Registering robot URL to MongoDB..."
    python3 "${SCRIPT_DIR}/register_robot_direct.py" "$CF_URL"
else
    echo "!!! Could not detect Cloudflare URL. Check log: $LOG_CF"
fi

# ========================
# Info
# ========================
echo
echo "================ Robot is running ================"
echo "Dogzilla server PID: $DOG_PID"
echo "Cloudflare PID:      $CF_PID"
echo "Access robot via:    $CF_URL"
echo "Press CTRL + C to stop."
echo "=================================================="

# Gi? script ch?y �? trap ho?t �?ng
while true; do
    sleep 1
done