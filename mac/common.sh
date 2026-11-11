# Shared settings for ./applypilot, ./dev.sh, and the launchd entry points. Sourced, not run.
# Callers set ROOT (the ApplyPilot folder) before sourcing this file.
API_PORT="${API_PORT:-8001}"
WEB_PORT="${WEB_PORT:-3000}"
# Private data (database, resumes, browser profile, logs, .env) lives outside the repository,
# so it can never be committed. The API computes the same default (app/core/config.py).
APPLYPILOT_HOME="${APPLYPILOT_HOME:-$HOME/Library/Application Support/ApplyPilot}"
export APPLYPILOT_HOME
LOGS="$APPLYPILOT_HOME/logs"
WEB="$ROOT/apps/web"
API="$ROOT/services/api"
LABEL_API="com.applypilot.api"
LABEL_WEB="com.applypilot.web"
AGENTS_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p "$LOGS" && chmod 700 "$APPLYPILOT_HOME" "$LOGS"
umask 077 # files ApplyPilot creates (logs, database, uploads) are readable only by you

port_pid() { lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -1; }
pid_dir() { lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p'; }
is_ours() { case "$(pid_dir "$1")" in "$ROOT"/*) return 0 ;; *) return 1 ;; esac; }
descendants() { for child in $(pgrep -P "$1"); do echo "$child"; descendants "$child"; done; }

# Stop the ApplyPilot server listening on a port, with its reloader and workers.
# Walks up to the server's top process (never past a process outside this folder, so the
# caller's shell is safe) and stops that process tree. Other programs are left alone.
stop_port() {
  pid="$(port_pid "$1")"
  [ -z "$pid" ] && return 0
  if ! is_ours "$pid"; then
    echo "Port $1 is used by another program ($(pid_dir "$pid")). Leaving it alone." >&2
    return 1
  fi
  top="$pid"
  while :; do
    parent="$(ps -o ppid= -p "$top" | tr -d ' ')"
    { [ -z "$parent" ] || [ "$parent" -le 1 ] || [ "$parent" = "$$" ] || ! is_ours "$parent"; } && break
    top="$parent"
  done
  kill $(descendants "$top") "$top" 2>/dev/null
  for _ in $(seq 1 20); do [ -z "$(port_pid "$1")" ] && return 0; sleep 0.5; done
  kill -9 $(descendants "$top") "$top" 2>/dev/null
  sleep 0.5
  return 0
}

agent_loaded() { launchctl print "$DOMAIN/$1" >/dev/null 2>&1; }
agents_loaded() { agent_loaded "$LABEL_API" || agent_loaded "$LABEL_WEB"; }

# Pause the production services until the next login or `./applypilot start`.
stop_agents() {
  for label in "$LABEL_WEB" "$LABEL_API"; do
    agent_loaded "$label" && launchctl bootout "$DOMAIN/$label" 2>/dev/null
  done
  for port in "$WEB_PORT" "$API_PORT"; do
    for _ in $(seq 1 20); do [ -z "$(port_pid "$port")" ] && break; sleep 0.5; done
  done
  return 0
}

# Keep each log under 5 MB, with one older copy.
rotate_log() {
  [ -f "$1" ] && [ "$(stat -f %z "$1")" -gt 5242880 ] && mv -f "$1" "$1.1"
  return 0
}

# The production web build is stale when web sources changed after it was made.
web_build_stale() {
  [ -f "$WEB/.next-prod/standalone/server.js" ] || return 0
  [ -n "$(cd "$WEB" && find src public next.config.ts package.json package-lock.json tailwind.config.ts postcss.config.js -newer .next-prod/BUILD_ID 2>/dev/null | head -1)" ]
}
