#!/bin/sh
# launchd entry point for the ApplyPilot API in production mode. Managed by ./applypilot.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/mac/common.sh"
rotate_log "$LOGS/api.log"
exec >>"$LOGS/api.log" 2>&1
echo "$(date '+%F %T') starting the API (production) on port $API_PORT"
pid="$(port_pid "$API_PORT")"
if [ -n "$pid" ]; then
  # Usually the development servers; launchd tries again shortly.
  echo "Port $API_PORT is in use by $(pid_dir "$pid"). Waiting." && sleep 20 && exit 1
fi
cd "$API" || exit 1
if [ ! -x .venv/bin/uvicorn ]; then
  echo "The Python environment is missing. Run ./dev.sh once to create it." && sleep 60 && exit 1
fi
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --timeout-graceful-shutdown 10
