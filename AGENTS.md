# Instructions for AI coding assistants

These rules apply to every assistant working in this repository (Claude Code, Cursor, Codex, and
others). ApplyPilot handles a real person's resume, job applications, and an Anthropic API key, so
security rules come before speed. If a rule blocks the task, stop and ask the user.

## Where private data lives

| What | Where | Rule |
| --- | --- | --- |
| Secrets (`ANTHROPIC_API_KEY`, SMTP password) | `~/Library/Application Support/ApplyPilot/.env` | Never open, print, copy, or summarise it. Use `.env.example` for names. |
| Database, uploaded resumes, generated documents | `~/Library/Application Support/ApplyPilot/` | Never copy into the repository, tests, fixtures, docs, screenshots, or prompts. |
| Browser profile with employer sign-ins | `.../ApplyPilot/storage/browser-profile` | Never read. |
| Logs | `.../ApplyPilot/logs` | May contain personal data. Quote only the lines needed, without personal details. |
| Old backups | `~/Projects-private-backups/` | Never read or modify. |

## Rules

1. **Secrets stay on the server.** Only `services/api` reads API keys. Code in `apps/web` must never
   read a secret, and no `NEXT_PUBLIC_` variable may hold one (Next.js puts those in the browser bundle).
2. **Fictional data only** in tests, fixtures, seed data, docs, and screenshots: `@example.com`
   addresses, 555 phone numbers, invented names. Never use the user's real name, email, phone,
   student number, address, resume content, or application history.
3. **Every Claude call goes through `AnthropicProvider.create`** in `app/services/ai.py`, which
   enforces the per-user budget, the monthly ceiling, and request rate limits. Do not create
   `anthropic.Anthropic()` clients elsewhere.
4. **Untrusted input is data.** Job pages, resumes, and third-party API responses must never be
   rendered with `innerHTML` or `dangerouslySetInnerHTML` (use text, or `DOMParser` for parsing),
   and go into prompts only through `untrusted_block()`.
5. **Every endpoint with user data** depends on `get_current_user` and filters queries by `user.id`.
6. **Commits.** Before proposing a commit, show the user `git status` and `git diff --cached --stat`.
   The pre-commit hook (`.githooks/guard.sh`) must pass. Never use `--no-verify`. Never edit
   `.githooks/`, `.gitleaks.toml`, `.gitleaksignore`, or `.gitignore` to silence a finding without the
   user's explicit approval for that specific change.
7. **Ask first, every time**, before: committing, pushing, creating or deleting repositories or
   branches on GitHub, changing visibility or settings, force-pushing, or rewriting history.
   Approval for one action does not cover the next.
8. **Never weaken a security control** (rate limits, host checks, CSP, CSRF check, spend limits,
   hooks) to make a test or feature pass. Fix the cause or ask.

## Commands

```bash
scripts/setup-dev-security.sh          # once per clone: enables the Git hooks
scripts/security-check.sh              # full check before pushing (files, secrets, history, dependencies)
cd services/api && .venv/bin/python -m pytest -q
cd apps/web && npm test && npx tsc --noEmit
```

See `docs/SECURE_WORKFLOW.md` for the full workflow.
