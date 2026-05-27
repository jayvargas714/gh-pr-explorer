#!/usr/bin/env bash
#
# Run this on your LOCAL machine (not on the remote box).
# It opens an SSH tunnel so http://localhost:5714 in your local browser
# reaches the gh-pr-explorer app running on the remote host's localhost:5714.
#
# Usage:
#   ./forward-port.sh user@remote-host
#   ./forward-port.sh myalias            # if you have an ~/.ssh/config Host entry
#
# Defaults below match the remote box this script was generated on; override
# by passing the host as the first argument.

set -euo pipefail

REMOTE="${1:-ubuntu@172.0.65.46}"   # <-- change to the host you SSH into
PORT="${2:-5714}"

echo "Forwarding local :${PORT} -> ${REMOTE} :${PORT}"
echo "Once connected, open http://localhost:${PORT} in your browser."
echo "Press Ctrl-C to close the tunnel."

# -N : don't run a remote command, just forward
# -L : local_port:remote_bind:remote_port  (remote_bind resolved on the remote side)
# Keepalives so the tunnel survives idle periods.
exec ssh -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L "${PORT}:localhost:${PORT}" \
  "${REMOTE}"
