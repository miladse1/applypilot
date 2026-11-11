#!/bin/sh
# launchd entry point for the ApplyPilot website in production mode. Managed by ./applypilot.
# Rebuilds first when the web code changed since the last build.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/mac/common.sh"
rotate_log "$LOGS/web.log"
exec >>"$LOGS/web.log" 2>&1
echo "$(date '+%F %T') starting the web app (production) on port $WEB_PORT"
pid="$(port_pid "$WEB_PORT")"
if [ -n "$pid" ]; then
  echo "Port $WEB_PORT is in use by $(pid_dir "$pid"). Waiting." && sleep 20 && exit 1
fi
if web_build_stale; then
  "$ROOT/mac/build-web.sh" || [ -f "$WEB/.next-prod/standalone/server.js" ] || { sleep 30; exit 1; }
fi
cd "$WEB/.next-prod/standalone" || exit 1
export NODE_ENV=production PORT="$WEB_PORT" HOSTNAME=127.0.0.1 API_URL="http://127.0.0.1:$API_PORT" NEXT_TELEMETRY_DISABLED=1
exec node server.js
