# Architecture

ApplyPilot is a monorepo.

- `apps/web` is a Next.js application. Browser calls go to `/api/v1`, and a route handler proxies them to the API with the session cookie.
- `services/api` is a FastAPI application. Domain rules live in `app/services`, HTTP handlers in `app/routers`, and tables in `app/models`.
- `packages/shared` lists status values used by the product language.
- PostgreSQL is the shared database in Docker. SQLite is enough for local demo and tests.

## Profile versus resume

The Master Professional Profile is the source of truth. An uploaded resume is evidence. Approving an extraction copies reviewed facts into the profile and records whether each fact was found in the document or added by the user.

A tailored resume is a projection of confirmed profile facts. Skills marked learning, skipped, unsure, or unverified are omitted. The truthfulness check rejects employers, titles, certifications, and numbers that are not already on the profile.

## Matching

Each requirement is classified as matched, partial, in progress, not possessed, or unverified. Unverified means the profile does not document it. The score uses assessed items and reports unknowns separately. It is not an ATS score and not a hiring probability.

Career interest is a separate score from saved preferences.

## Applications

Status changes go through a server-side transition map. Approval stores the draft version and document ids. Editing answers, the resume, or the profile invalidates that approval. Submission requires a still-valid approval.

`simulated` writes a confirmation id prefixed with `sim_` and `is_live_submission=false`. `manual` stops at `manual_action_required` until the user explicitly confirms. Any other method is rejected. There is no live provider.

## Job text

Descriptions are data. The deterministic extractor only emits catalog skills and a few structured patterns such as years, degrees, and work authorization. Optional model output is discarded unless each requirement is grounded in the description text.

## Jobs

`services/job_sources.py` holds one adapter per platform. `services/employers.py` holds the monitored employers, and `services/taxonomy.py` holds the role, level, and location classifier.

A run (`services/job_sync.py`) works like this:
- It builds a `SearchPlan` from the user's saved search.
- It fetches all sources in parallel in a background thread, and the UI polls its progress.
- It keeps only postings that fit the plan, and stores a slightly wider set than the default view.
- It merges duplicates by company, title, and city, preferring the employer's own posting.
- It expires postings that a full-catalog board no longer lists or that are past their closing date.

`services/job_search.py` filters and ranks stored postings for the Jobs page. It reports how many were hidden by each filter.

## Resumes

`services/resume_layout.py` reads a PDF (PyMuPDF) or DOCX into styled lines and a style profile: font, sizes, margins, rules, bullet glyph, and indents. `services/resume_parser.py` turns those lines into a document model (sections, entries, bullets, skill groups, in the original order and wording) plus profile facts. `services/tailoring.py` edits that document model for a job and records every change. `services/resume_render.py` renders it back as PDF and DOCX in the original typography, fitting the original page count. When the original is a DOCX, the DOCX download is the user's own file edited in place.
