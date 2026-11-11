#!/usr/bin/env bash
# Full security check. Run before pushing, before changing repository visibility, and after
# dependency updates. Nothing is printed that could reveal a secret.
#
#   scripts/security-check.sh          all checks
#   scripts/security-check.sh --quick  skip the dependency audits (no network)
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
DATA="${APPLYPILOT_HOME:-$HOME/Library/Application Support/ApplyPilot}"
fail=0
section() { printf '\n\033[1m%s\033[0m\n' "$*"; }
bad() { printf '\033[31mFAIL\033[0m  %s\n' "$*"; fail=1; }
ok() { printf '\033[32mok\033[0m    %s\n' "$*"; }

section "1. Files, private details, and secrets (working tree and full history)"
if .githooks/guard.sh all; then ok "git-guard"; else bad "git-guard (details above)"; fi

section "2. Private data stays outside the repository"
leftovers="$(find . \( -path ./apps/web/node_modules -o -path ./services/api/.venv -o -path './services/api/.venv.*' -o -path ./.git -o -name .mypy_cache -o -name .pytest_cache -o -name .ruff_cache \) -prune -o \
  \( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' -o -name '*.sqlite*' -o -name '.env' -o -name 'browser-profile' -o -name '.logs' -o -name backups \) -print 2>/dev/null)"
if [ -n "$leftovers" ]; then
  printf '%s\n' "$leftovers" | sed 's/^/      /'
  bad "private data found inside the repository folder (move it to $DATA)"
else
  ok "no databases, .env files, logs, backups, or browser profiles in the repository folder"
fi
if [ -d "$DATA" ]; then
  perms="$(stat -f '%Lp' "$DATA" 2>/dev/null || stat -c '%a' "$DATA")"
  [ "$perms" = 700 ] && ok "data folder is private (mode 700)" || bad "data folder mode is $perms; run: chmod 700 \"$DATA\""
  if [ -f "$DATA/.env" ]; then
    perms="$(stat -f '%Lp' "$DATA/.env" 2>/dev/null || stat -c '%a' "$DATA/.env")"
    [ "$perms" = 600 ] && ok ".env is readable only by you (mode 600)" || bad ".env mode is $perms; run: chmod 600 \"$DATA/.env\""
  fi
fi

section "3. No secret values in the built web app"
if [ -f "$DATA/.env" ]; then
  found=0
  for build in apps/web/.next apps/web/.next-prod; do
    [ -d "$build" ] || continue
    python3 -I - "$DATA/.env" "$build" <<'PY' || found=1
import os, re, sys
env, build = sys.argv[1], sys.argv[2]
values = []
for line in open(env):
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.rstrip("\n").split("=", 1)
        value = value.strip().strip("\"'")
        if len(value) >= 12 and re.search(r"KEY|SECRET|TOKEN|PASSWORD", key):
            values.append((key, value.encode()))
hits = set()
for folder, _dirs, files in os.walk(build):
    for name in files:
        try:
            data = open(os.path.join(folder, name), "rb").read()
        except OSError:
            continue
        hits.update(key for key, value in values if value in data)
for key in sorted(hits):
    print(f"      {key} appears in {build}")
sys.exit(1 if hits else 0)
PY
  done
  [ "$found" -eq 0 ] && ok "no .env secret values in web build output" || bad "secret values found in web build output"
else
  ok "no private .env found; skipped"
fi

if [ "${1:-}" != "--quick" ]; then
  section "4. Known vulnerabilities in dependencies"
  if command -v pip-audit >/dev/null 2>&1; then
    if pip-audit -r services/api/requirements-lock.txt --no-deps --disable-pip --progress-spinner off >/tmp/pip-audit.$$ 2>&1; then ok "Python (pip-audit)"; else cat /tmp/pip-audit.$$; bad "Python dependencies"; fi
    rm -f /tmp/pip-audit.$$
  else
    bad "pip-audit is not installed (brew install pip-audit)"
  fi
  if (cd apps/web && npm audit --omit=dev --audit-level=moderate >/tmp/npm-audit.$$ 2>&1); then ok "JavaScript (npm audit)"; else tail -20 /tmp/npm-audit.$$; bad "JavaScript dependencies"; fi
  rm -f /tmp/npm-audit.$$
fi

echo
if [ "$fail" -ne 0 ]; then echo "Security check failed."; exit 1; fi
echo "Security check passed."
