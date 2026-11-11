# Secure development workflow

How to change ApplyPilot, alone or with an AI assistant, without leaking secrets or personal data.

## Once per computer or clone

```bash
brew install gitleaks pip-audit
scripts/setup-dev-security.sh     # enables .githooks, creates ~/.config/git-guard/private-patterns.txt
```

Open `~/.config/git-guard/private-patterns.txt` and add your personal email, phone number (with and
without dashes), student number, and street address, one per line. The hooks block any commit that
contains them. The file never leaves your computer.

## Where things live

| | Location | In Git? |
| --- | --- | --- |
| Source code, fictional test data | this repository | yes |
| `.env` (API keys, SMTP password) | `~/Library/Application Support/ApplyPilot/.env` | never |
| Database, resumes, documents, browser profile, logs | `~/Library/Application Support/ApplyPilot/` | never |
| Old backups | `~/Projects-private-backups/` | never |

Set or change keys with `./configure.sh ai` or `./configure.sh email`; never paste keys into chat
with an AI assistant or into source files.

## Everyday loop

1. **Develop.** `./dev.sh` (or `./applypilot dev`). Claude Code and Cursor read `AGENTS.md`;
   Claude Code also enforces `.claude/settings.json` (asks before commit/push, denies reading `.env`).
2. **Test.** `cd services/api && .venv/bin/python -m pytest -q` and `cd apps/web && npm test`.
3. **Review.** Before staging, read the diff yourself:
   ```bash
   git status
   git diff                 # what changed
   git add -p               # stage hunk by hunk instead of `git add .`
   git diff --cached --stat # exactly what the commit will contain
   ```
   Check screenshots for real names, emails, and job or application data.
4. **Commit.** `git commit`. The pre-commit hook checks blocked file types, sizes, browser-exposed
   secrets, your private details, and secrets (gitleaks). If it blocks, read the message; do not use
   `--no-verify`.
5. **Check before pushing.** `scripts/security-check.sh` (working tree, full history, data-folder
   permissions, built web app, dependency audits).
6. **Push.** `git push`. The pre-push hook scans every outgoing commit again.
7. **Watch.** GitHub runs the Security workflow on every push and weekly. Dependabot opens
   grouped update pull requests on Mondays and security fixes immediately; review and merge them
   after CI passes.

## If something goes wrong

- **The hook blocks a file that should be committed** (for example a fictional PDF fixture): move
  it under `services/api/tests/fixtures/` or add a narrow, reviewed line to `.githooks/allowed-paths`.
- **The hook reports a false-positive secret:** add its fingerprint (printed by gitleaks) to
  `.gitleaksignore` with a comment saying why.
- **A real secret was committed but not pushed:** `git reset --soft HEAD~1`, remove the secret,
  commit again. Rotate the secret anyway if it was ever pushed or shared.
- **A real secret reached GitHub:** rotate it immediately (for Anthropic: console.anthropic.com →
  API keys), then clean history only with a deliberate plan; deleting the file in a new commit
  does not remove it from history.

## Publishing

Before making this repository public or pushing to a public remote:

1. `scripts/security-check.sh` passes.
2. `gitleaks git --redact` over the full history is clean (part of the check above).
3. `git ls-files` contains nothing from the "never" rows above.
4. Screenshots and docs show demo data only.
5. On GitHub: Settings → Code security → enable secret scanning, push protection, Dependabot
   alerts and security updates, and private vulnerability reporting.
