# Security

## Reporting a vulnerability

Please report security problems privately through GitHub: **Security → Report a vulnerability** on
this repository. Do not open a public issue. You will get a reply within a week.

## Security model

ApplyPilot is a single-user application that runs on the user's own computer. It is not designed
or hardened for hosting on the public internet.

| Area | Control |
| --- | --- |
| Private data | Database, uploaded resumes, generated documents, browser profile, logs, and `.env` live in `~/Library/Application Support/ApplyPilot` (mode 700), outside the repository. |
| Network exposure | The API and web app listen on `127.0.0.1` only. The API refuses requests addressed to other host names (DNS-rebinding protection). Docker publishes ports on `127.0.0.1` only. |
| Passwords | PBKDF2-SHA256 with 600,000 iterations and a per-user salt. Inputs over 200 characters are refused before hashing. |
| Sessions | 256-bit random tokens; only their SHA-256 hash is stored. 12-hour expiry, revoked on sign-out. The browser holds the token in an `HttpOnly`, `SameSite=Lax` cookie set by the web app, never in JavaScript. Password reset signs out every session; password change signs out every other session. |
| Abuse limits | Failed sign-ins (20 per account and 50 per client per 10 minutes), registrations (10 per hour), and reset requests (10 per hour, 3 per account) are rate-limited. Sign-up closes once an account exists (`ALLOW_REGISTRATION=true` reopens it). Reset responses and sign-in errors do not reveal whether an account exists. |
| Cross-site requests | The web app's API proxy accepts writes only from its own origin. CORS allows only the configured origin. |
| Browser hardening | Content-Security-Policy, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, and `Permissions-Policy` on every page; `Cache-Control: no-store` on API responses. Third-party HTML is never inserted into the page. |
| AI keys and cost | The Anthropic key is read only by the API and never sent to the browser. Every model call passes a per-user spending limit, an installation-wide monthly ceiling, and per-user request rate limits. Job pages and resumes are passed to the model as clearly marked untrusted data. |
| Repository | Pre-commit and pre-push hooks (`.githooks/`) block secrets, personal details, and sensitive file types; CI repeats the checks over the full history and audits dependencies weekly. |

## Known limitations

- Rate limits are kept in memory: they reset when the API restarts and assume one API process.
- The session cookie is marked `Secure` only when `COOKIE_SECURE=true` (set it behind HTTPS).
- Browser-assisted applications run a real Chrome profile that keeps employer sign-ins. Anyone with
  access to your macOS account can use them.
