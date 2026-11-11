# Running ApplyPilot

Detailed instructions. For an overview, see the [README](../README.md).

## Run it locally

Requirements: Python 3.12+, Node.js 22+.

```bash
./dev.sh          # starts the API on :8001 and the web app on :3000
./dev.sh stop     # stops both
```

Open http://localhost:3000 and create your account (sign-up closes once an account exists; `ALLOW_REGISTRATION=true` reopens it). On first run the script creates the Python environment from `requirements-lock.txt`. Private data, logs, and keys live in `~/Library/Application Support/ApplyPilot/` (see [Where data lives](#where-data-lives)).

To run the pieces by hand, use the virtual environment's own `uvicorn`, since it is not on your PATH unless the venv is activated:

```bash
cd services/api && .venv/bin/uvicorn app.main:app --reload --port 8001
cd apps/web && npm run dev        # apps/web/.env.local points it at port 8001
```

The database schema upgrades itself on start (it only adds tables and columns). If you used an earlier version, back up `~/Library/Application Support/ApplyPilot/applypilot.db` and run this once:

```bash
cd services/api && .venv/bin/python -m app.scripts.upgrade_data --i-have-a-backup
```

It re-reads stored resumes with the new parser and rebuilds the resume-derived parts of each profile. Skills and answers you confirmed are kept. It also classifies stored jobs.

Docker (PostgreSQL, ports on 127.0.0.1 only): put `POSTGRES_PASSWORD` and optional keys in a `.env` next to `docker-compose.yml`, then `docker compose up --build`.

## Use it like a Mac app

```bash
./applypilot install      # once: start at login, add "ApplyPilot Control" to ~/Applications
```

After that, ApplyPilot runs in production mode in the background. It starts when you log in and restarts itself if it crashes. To get a Dock icon, open http://localhost:3000 in Chrome and choose ⋮ → Cast, save, and share → Install page as app. ApplyPilot then opens in its own window from the Dock, Launchpad, or Spotlight.

**ApplyPilot Control** (in ~/Applications) opens the app and starts, stops, or restarts it, switches between production and development mode, and shows logs. The same actions work from a terminal:

| Command | What it does |
| --- | --- |
| `./applypilot status` | Mode (production, development, stopped) and health |
| `./applypilot start` / `stop` / `restart` | Control the production services. Start and restart rebuild the web app first if its code changed. |
| `./applypilot dev` | Development mode: pauses production and runs `./dev.sh` with hot reload |
| `./applypilot prod` | Back to production mode |
| `./applypilot uninstall` | Remove auto-start and the Control app. Data is untouched. |

When you continue coding, run `./dev.sh` (or `./applypilot dev`) as before. It pauses the production services automatically. They come back with `./applypilot prod` or at your next login. Production builds go to `apps/web/.next-prod`, so development (`.next`) never overwrites them. Both modes use the same database, settings, and logs (`~/Library/Application Support/ApplyPilot/logs/`). The services are launchd agents in `~/Library/LaunchAgents/com.applypilot.{api,web}.plist`. macOS lists them under System Settings → General → Login Items.

## Browser-assisted applications

Select approved applications on the Applications page and choose **Apply with ApplyPilot**. ApplyPilot opens each one in its own Chrome window (a separate profile in the data folder's `storage/browser-profile`, so employer sign-ins are kept), fills in the form, uploads the approved tailored resume and cover letter, and either submits or stops for your review, whichever you chose.

| Site | What happens |
| --- | --- |
| Greenhouse, Lever, Ashby | Filled in and submitted. No account needed. |
| Workday | You sign in or create the employer's account once in the ApplyPilot window; it continues by itself after that and fills each step. |
| Other employer sites | Opens the form and fills what it recognises; you finish the rest. |
| LinkedIn, Indeed, university portals | Not automated: those sites do not allow it. |

- **Answers** come only from your profile, Settings → Application autofill, answers you saved earlier, and the answers you approved for that application. A required question it cannot answer pauses the run and appears on the Applications page; answer it there (it is remembered for next time) or in the browser window. Claude Haiku may map an unusual wording onto one of those facts (cached, within your AI spending limit); it never writes new answers.
- **Voluntary questions** (gender, ethnicity, veteran, disability) are left blank or declined only if you chose that in Settings. Privacy-notice checkboxes are ticked only if you allowed it.
- **It pauses** for sign-ins, CAPTCHAs, verification codes, and sites that block automation. Sign-ins and CAPTCHAs are detected as soon as you finish, and the run continues. It never solves CAPTCHAs, never fills hidden "honeypot" fields, and does not disguise itself as a person: Chrome shows that it is being controlled by automated software.
- **Submitted means confirmed.** An application is marked *Submitted by ApplyPilot (employer confirmed)* only when the employer's confirmation page appears; the page text and a screenshot are kept. If Submit was clicked but no confirmation appeared, it is marked *not confirmed* until you check.
- Runs that were in progress when ApplyPilot restarts are stopped safely: nothing is re-sent automatically.

## Keys and email

Secrets live only in `~/Library/Application Support/ApplyPilot/.env`, outside the repository. The setup script keeps it readable only by you:

```bash
./configure.sh ai       # asks for your Anthropic key (hidden), saves it, checks it with a real request, restarts
./configure.sh email    # asks for SMTP settings, sends a test email, restarts
```

| Setting | What it enables | Where to get it |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude rewrites bullets and summaries, writes cover letters, double-checks extraction, and runs the assistant. Uses `claude-sonnet-5-5` for rewriting and the assistant and `claude-haiku-5-5` for extraction checks; Opus 5.5 is optional in Settings. | https://console.anthropic.com/settings/keys |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Password-reset emails. Links work once and expire after 30 minutes. | Your email provider. For Gmail: `smtp.gmail.com`, port 587, and an app password. |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Adzuna Canada aggregator, which adds many more postings | https://developer.adzuna.com/signup |

### AI cost

Job classification, requirement and skill extraction, matching, and ranking run locally and cost nothing. Claude is called only for:

| Feature | Model | Typical cost |
| --- | --- | --- |
| Resume tailoring (one job) | Sonnet 5.5 | about $0.02–0.03 (measured $0.016) |
| Cover letter | Sonnet 5.5 | about $0.01–0.02 |
| Assistant message | Sonnet 5.5 | about $0.01–0.03, depending on tool steps (measured $0.013) |
| Extraction check (only when a role or school needs review) | Haiku 5.5 | under $0.002 |
| Connection test | Haiku 5.5 | under $0.0001 |

Settings → AI shows estimated spend by day, month, feature, and model, and lets you choose Opus 5.5 (about 2× the cost) and a spending limit (default `AI_SPEND_LIMIT_USD=4.50`). Every call also passes an installation-wide monthly ceiling (`AI_MONTHLY_LIMIT_USD=25.00`) and per-user rate limits (`AI_REQUESTS_PER_MINUTE=30`, `AI_REQUESTS_PER_HOUR=300`). When a limit is reached, ApplyPilot keeps working with its built-in tailoring and rules. Identical tailoring and cover-letter requests reuse the earlier result; "Regenerate" asks Claude again. Estimates use Anthropic's list prices; the Anthropic console shows what you are billed.

Reset tokens are never sent to the browser. In development without SMTP, the reset link is written to the API log in the data folder. With `ENVIRONMENT=production` that fallback is off. Set `APP_BASE_URL` to the site's public address so emailed links point to it. Settings → AI → "Test connection" checks the model from the app.

## Tests

```bash
cd services/api && .venv/bin/pytest
cd apps/web && npm test
```

Tests run offline with an in-memory database.

## Where data lives

| What | Location |
| --- | --- |
| Database, uploaded resumes, generated documents, browser profile | `~/Library/Application Support/ApplyPilot/` (mode 700) |
| Keys and SMTP settings | `~/Library/Application Support/ApplyPilot/.env` (mode 600) |
| Logs | `~/Library/Application Support/ApplyPilot/logs/` |

Set `APPLYPILOT_HOME` to use another folder. Nothing private is stored in the repository.
