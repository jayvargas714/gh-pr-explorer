#!/bin/bash

PORT=5714

# Kill any existing process on the port
existing_pid=$(lsof -ti :$PORT 2>/dev/null)
if [ -n "$existing_pid" ]; then
  echo "Stopping existing process on port $PORT (PID: $existing_pid)..."
  kill "$existing_pid" 2>/dev/null
  sleep 1
  # Force kill if still running
  if kill -0 "$existing_pid" 2>/dev/null; then
    kill -9 "$existing_pid" 2>/dev/null
  fi
fi

# Build frontend
cd frontend && npm run build && cd ..

# Trap signals so Ctrl+C cleanly stops the server
cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$server_pid" 2>/dev/null
  wait "$server_pid" 2>/dev/null
  echo "Server stopped."
  exit 0
}
trap cleanup INT TERM

# Start Flask in background so trap can catch signals
python app.py &
server_pid=$!

# Wait for server process
wait "$server_pid"
