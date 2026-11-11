#!/bin/sh
# Start the ApplyPilot API and web app for local development.
#   ./dev.sh          start both (API on 8001, web on 3000)
#   ./dev.sh stop     stop both
#   ./dev.sh status   show what is running
# Logs: ~/Library/Application Support/ApplyPilot/logs/api.log and web.log
# If ApplyPilot is installed as a Mac app, its production services are paused first
# (until the next login or `./applypilot prod`).
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
. "$ROOT/mac/common.sh"

case "${1:-start}" in
  stop)
    stop_agents; stop_port "$API_PORT"; stop_port "$WEB_PORT"; echo "Stopped."; exit 0 ;;
  status)
    for port in "$API_PORT" "$WEB_PORT"; do
      pid="$(port_pid "$port")"
      if [ -n "$pid" ]; then echo "port $port: pid $pid in $(pid_dir "$pid")"; else echo "port $port: free"; fi
    done
    exit 0 ;;
esac

if [ ! -x "$ROOT/services/api/.venv/bin/uvicorn" ]; then
  echo "Creating the Python environment…"
  # requirements-lock.txt is tested on Python 3.14; prefer it even when python3 points elsewhere.
  PY="${PYTHON:-$(command -v python3.14 || command -v python3)}"
  "$PY" -m venv "$ROOT/services/api/.venv" && "$ROOT/services/api/.venv/bin/python" -m pip install -q -r "$ROOT/services/api/requirements-lock.txt" || exit 1
fi
[ -d "$ROOT/apps/web/node_modules" ] || (cd "$ROOT/apps/web" && npm install) || exit 1

if agents_loaded; then
  stop_agents
  echo "Paused the ApplyPilot app (production mode). Switch back with ./applypilot prod."
fi
# Replace earlier ApplyPilot servers so the newest code always runs.
stop_port "$API_PORT" || { echo "Choose another port: API_PORT=8002 ./dev.sh" >&2; exit 1; }
stop_port "$WEB_PORT" || { echo "Choose another port: WEB_PORT=3001 ./dev.sh" >&2; exit 1; }

# Redirect the whole subshell so nothing keeps this script's output open (callers can wait on it).
(cd "$ROOT/services/api" && exec nohup .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port "$API_PORT") < /dev/null > "$LOGS/api.log" 2>&1 &
printf 'Starting API'
ok=""
for _ in $(seq 1 60); do
  if curl -s "http://127.0.0.1:$API_PORT/api/v1/health" | grep -q '"integrations"'; then ok=1; break; fi
  printf '.'; sleep 1
done
echo
if [ -z "$ok" ]; then echo "The API did not start. See $LOGS/api.log:" >&2; tail -20 "$LOGS/api.log" >&2; exit 1; fi

# -H 127.0.0.1: reachable from this computer only (next dev otherwise listens on the whole network).
(cd "$ROOT/apps/web" && API_URL="http://127.0.0.1:$API_PORT" exec nohup npx next dev -H 127.0.0.1 -p "$WEB_PORT") < /dev/null > "$LOGS/web.log" 2>&1 &
printf 'Starting web app'
ok=""
for _ in $(seq 1 90); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$WEB_PORT/login")" = "200" ]; then ok=1; break; fi
  printf '.'; sleep 1
done
echo
if [ -z "$ok" ]; then echo "The web app did not start. See $LOGS/web.log." >&2; exit 1; fi
if ! curl -s "http://localhost:$WEB_PORT/api/v1/health" | grep -q '"integrations"'; then
  echo "The web app cannot reach the API through its proxy. See $LOGS/web.log." >&2; exit 1
fi
echo "ApplyPilot is running: http://localhost:$WEB_PORT"
echo "API docs: http://127.0.0.1:$API_PORT/docs"
