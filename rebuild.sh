#!/usr/bin/env bash
# rebuild.sh — kill the running daemon and restart it from source
set -euo pipefail

APP="bazzite-clipboard"
BIN="${HOME}/.local/bin/${APP}"

echo "Stopping ${APP}..."
if pkill -f "python.*bazzite_clipboard" 2>/dev/null; then
    sleep 0.4
else
    echo "(no running instance found)"
fi

echo "Starting ${APP}..."
"${BIN}" &

echo "Done — daemon restarted (PID $!)."
