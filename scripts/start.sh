#!/usr/bin/env bash
# Start the assistant and open it in a browser.
#
#   ./scripts/start.sh          the staff chat
#   ./scripts/start.sh admin    the owner's desk
#   ./scripts/start.sh 8080     a different port
#
# Stop it with Ctrl-C. This is the only command a client needs day to day.

set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8000
PAGE=""
for arg in "$@"; do
  case "$arg" in
    admin) PAGE="/admin" ;;
    [0-9]*) PORT="$arg" ;;
    *) echo "Usage: ./scripts/start.sh [admin] [port]"; exit 1 ;;
  esac
done

if [ ! -x .venv/bin/uvicorn ]; then
  echo "The environment isn't set up yet. Run:"
  echo "  python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

# A server already on this port is almost always a forgotten copy of this one.
if lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Something is already running on port $PORT."
  echo "Use it at http://localhost:$PORT$PAGE, or stop it with:"
  echo "  pkill -f 'uvicorn app.web:api'"
  exit 1
fi

echo "Starting the assistant on http://localhost:$PORT$PAGE"
echo "Press Ctrl-C to stop."

# Open the browser once the server answers, without blocking the server itself.
( for _ in $(seq 1 40); do
    if curl -sf -o /dev/null "http://localhost:$PORT/"; then
      command -v open >/dev/null && open "http://localhost:$PORT$PAGE"
      break
    fi
    sleep 0.5
  done ) &

exec .venv/bin/uvicorn app.web:api --port "$PORT" --log-level warning
