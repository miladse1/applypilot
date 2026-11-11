# Integrations

## Job sources

Every source is a public listing API or feed that the employer or board publishes. Reading is paced per host, and Job Bank's 5-second crawl delay is respected. Listing access never grants permission to submit applications.

| Source | How it is read | Notes |
| --- | --- | --- |
| Workday career sites (TD, RBC, BMO, CIBC, Manulife, Sun Life, Thomson Reuters, GM, NVIDIA, Salesforce, Autodesk, Cisco, Adobe, PwC) | The JSON listing the career site itself uses, filtered to Canada through the site's country facet. Details are fetched only for relevant titles. | Gives the posting date and the closing date, so expired roles are dropped. |
| SuccessFactors (Scotiabank, Rogers, Bell) | The employer's published RSS feed (`/feeds/{keyword}/`). | |
| Greenhouse, Lever, Ashby boards (Stripe, Lyft, Pinterest, Geotab, Wealthsimple, Cohere, 1Password, PointClickCare, and others) | Public board APIs. | Full catalogs: postings that disappear are marked closed. |
| Amazon Jobs | `amazon.jobs/en/search.json`, filtered to Canada. | |
| IBM Careers | IBM's public careers search API, filtered to Canada. | Full text is read from the posting page when opened. |
| AMD | The iCIMS Jibe `/api/jobs` endpoint, filtered to Canada. | |
| Job Bank (Government of Canada) | The search Atom feed. | Full text is read from the posting's schema.org markup when opened. |
| Jobicy, Himalayas, Remotive | Public APIs. | Only roles open to candidates in Canada are kept. |
| Adzuna | Search API with `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`, country `ca`. | Optional. |
| Arbeitnow | Public feed. | Off by default (Europe). |
| Your own employers | Paste any Workday, Greenhouse, Lever, or Ashby careers URL in Job searches → Sources. | |
| Import | Paste a posting URL. ATS links are read through their APIs; other employer pages through schema.org `JobPosting` data. | |

Not read automatically: LinkedIn, Indeed, Glassdoor, TalentEgg, ZipRecruiter, Handshake, and university portals such as Experience York or Lassonde co-op. Their terms or sign-in walls prohibit it. ApplyPilot offers saved-search links for them, plus a "Send to ApplyPilot" bookmarklet that passes the page you are viewing into the import form.

## AI

`AI_PROVIDER=auto` uses Claude (Anthropic SDK; `claude-sonnet-5-5` for writing and the assistant, `claude-haiku-5-5` for checks, `claude-opus-5-5` optional; adaptive thinking, structured JSON outputs, server-side refusal fallback) when `ANTHROPIC_API_KEY` is set. `openai` remains available for the JSON tasks. Job and resume text is passed as untrusted data. Every model output is validated before use:

- resume rewrites must not add numbers, tools, or names;
- extraction fixes must appear verbatim in the resume;
- cover letters must not contain unsupported numbers.

The assistant's tools cannot approve or submit.

## Submission

- `manual`: you finish the employer form, then confirm in ApplyPilot. The record is labeled "Submitted by you".
- `simulated`: demo mode only. The record is labeled and never sent anywhere.
- **Browser-assisted** (Applications → Apply with ApplyPilot): ApplyPilot fills the approved application in a visible Chrome window on Greenhouse, Lever, Ashby, and Workday forms, then submits or stops for review. It is marked *Submitted by ApplyPilot (employer confirmed)* only when the employer's confirmation page appears. It pauses for sign-ins and CAPTCHAs and never solves them. See [RUNNING.md](RUNNING.md#browser-assisted-applications).

There is no server-to-server submission integration: `/api/v1/health` reports `live_submission: []`.
