#!/bin/sh
# Store secrets for ApplyPilot in the private data folder (outside this repository) and check
# that they work.
#   ./configure.sh ai       Anthropic API key for Claude
#   ./configure.sh email    SMTP settings for password-reset email
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
DATA="${APPLYPILOT_HOME:-$HOME/Library/Application Support/ApplyPilot}"
ENV="$DATA/.env"
PY="$ROOT/services/api/.venv/bin/python"
mkdir -p "$DATA" && chmod 700 "$DATA"
(umask 077 && [ -f "$ENV" ] || touch "$ENV")
chmod 600 "$ENV"

set_value() {  # set_value KEY VALUE  (replaces an existing line or appends one)
  "$PY" - "$ENV" "$1" "$2" <<'PYEOF'
import sys
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(path).read().splitlines()
lines = [line for line in lines if not line.startswith(key + "=")]
lines.append(f"{key}={value}")
open(path, "w").write("\n".join(lines) + "\n")
PYEOF
}

ask_secret() {  # ask_secret PROMPT -> prints the value; input is not echoed
  printf '%s' "$1" >&2
  stty -echo 2>/dev/null || true
  IFS= read -r value
  stty echo 2>/dev/null || true
  echo >&2
  printf '%s' "$value"
}

case "${1:-}" in
  ai)
    echo "Create a key at https://console.anthropic.com/settings/keys (it starts with sk-ant-)."
    key="$(ask_secret 'Paste your Anthropic API key (input hidden): ')"
    case "$key" in sk-ant-*) ;; *) echo "That does not look like an Anthropic key." >&2; exit 1 ;; esac
    set_value ANTHROPIC_API_KEY "$key"
    set_value AI_PROVIDER auto
    grep -q '^ANTHROPIC_MODEL=' "$ENV" || set_value ANTHROPIC_MODEL claude-sonnet-5-5
    echo "Checking the key with a real request…"
    (cd "$ROOT/services/api" && "$PY" - <<'PYEOF'
from app.core.config import get_settings
from app.services.ai import AIError, get_provider
provider = get_provider(get_settings(), tier="fast")
schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "reply": {"type": "string"}}, "required": ["ok", "reply"], "additionalProperties": False}
try:
    result = provider.structured(system="Connection check.", user="Reply with ok=true and a three-word greeting.", schema=schema, max_tokens=2000, effort="low")
    print(f"Claude ({provider.model}) answered: {result.get('reply')}")
except AIError as exc:
    raise SystemExit(f"The key was saved, but the check failed: {exc}")
PYEOF
)
    ;;
  email)
    echo "Enter SMTP settings from your email provider (for Gmail: smtp.gmail.com, port 587, and an app password)."
    printf 'SMTP host: '; read -r host
    printf 'SMTP port [587]: '; read -r port; port="${port:-587}"
    printf 'Security (starttls/ssl/none) [starttls]: '; read -r security; security="${security:-starttls}"
    printf 'SMTP username: '; read -r username
    password="$(ask_secret 'SMTP password (input hidden): ')"
    printf 'From address (e.g. ApplyPilot <you@example.com>): '; read -r sender
    printf 'Send a test email to: '; read -r test_to
    set_value SMTP_HOST "$host"; set_value SMTP_PORT "$port"; set_value SMTP_SECURITY "$security"
    set_value SMTP_USERNAME "$username"; set_value SMTP_PASSWORD "$password"; set_value SMTP_FROM "$sender"
    (cd "$ROOT/services/api" && TEST_TO="$test_to" "$PY" - <<'PYEOF'
import os
from app.services.email import EmailError, send_email
try:
    send_email(os.environ["TEST_TO"], "ApplyPilot email works", "This is a test from ApplyPilot. Password-reset emails will be sent this way.")
    print("Test email sent.")
except EmailError as exc:
    raise SystemExit(f"Settings were saved, but sending failed: {exc}")
PYEOF
)
    ;;
  *)
    echo "Usage: ./configure.sh ai | email" >&2; exit 1 ;;
esac
echo "Saved to $ENV (outside the repository, readable only by you). Restarting ApplyPilot…"
if [ -f "$HOME/Library/LaunchAgents/com.applypilot.api.plist" ]; then
  "$ROOT/applypilot" restart
else
  "$ROOT/dev.sh"
fi
