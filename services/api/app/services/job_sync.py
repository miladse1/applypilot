"""Discover, classify, deduplicate, expire, and match job postings."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import ensure_utc
from app.models import (
    BackgroundTask,
    JobMatch,
    JobPosting,
    JobRequirement,
    JobSearch,
    JobSearchSchedule,
    Profile,
    QualificationVerificationRequest,
    SearchProfile,
    User,
    UserSettings,
)
from app.services.analysis import analyze_job_text
from app.services.employers import EMPLOYERS, Employer, employer_from_dict, parse_board_token
from app.services.http_fetch import Http
from app.services.job_sources import (
    BOARD_SOURCES,
    Adapter,
    DemoCatalogAdapter,
    NormalizedJob,
    ProviderError,
    SearchPlan,
    SearchQuery,
    adapter_for_employer,
    board_adapter,
    fingerprint,
)
from app.services.jsonutil import dumps, loads
from app.services.matching import build_assessment, needs_verification, verification_prompt
from app.services.profile_ops import get_profile

log = logging.getLogger(__name__)

# Employer-direct postings win over aggregator copies of the same role.
SOURCE_PRIORITY = {
    "greenhouse": 5, "lever": 5, "ashby": 5, "workday": 5, "successfactors": 5, "amazon": 5, "ibm": 5, "jibe": 5,
    "import": 5, "manual": 5, "yorku": 4, "jobbank": 3, "linkedin": 2, "adzuna": 2, "himalayas": 2, "jobicy": 2, "remotive": 1, "arbeitnow": 0, "sample": 0,
}
SOURCE_NAMES = {
    "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday", "successfactors": "SuccessFactors",
    "amazon": "Amazon Jobs", "ibm": "IBM Careers", "jibe": "Careers site", "jobbank": "Job Bank", "adzuna": "Adzuna",
    "himalayas": "Himalayas", "jobicy": "Jobicy", "remotive": "Remotive", "arbeitnow": "Arbeitnow", "manual": "Added by you",
    "import": "Imported by you", "sample": "Practice listing", "yorku": "Experience York", "linkedin": "LinkedIn",
}


# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------


def user_settings_row(db: Session, user: User | None) -> UserSettings | None:
    if user is None:
        return None
    return db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))


def source_overrides(row: UserSettings | None) -> dict[str, bool]:
    value = loads(row.disabled_sources, {}) if row else {}
    if isinstance(value, list):  # older shape: list of disabled keys
        return {key: False for key in value}
    return value if isinstance(value, dict) else {}


def work_authorization(row: UserSettings | None) -> dict:
    value = loads(row.work_authorization, {}) if row else {}
    return value if isinstance(value, dict) else {}


def monitored_employers(settings: Settings, row: UserSettings | None) -> list[Employer]:
    employers: list[Employer] = list(EMPLOYERS) if settings.public_job_sources else []
    tokens = [item.strip() for item in settings.job_board_tokens.split(",") if item.strip()]
    if row:
        tokens.extend(loads(row.job_board_tokens, []))
    for token in tokens:
        employer = parse_board_token(token)
        if employer:
            employers.append(employer)
    if row:
        for data in loads(row.custom_employers, []):
            try:
                employers.append(employer_from_dict(data))
            except (KeyError, TypeError, ValueError):
                continue
    unique: dict[str, Employer] = {}
    for employer in employers:
        unique.setdefault(employer.source_key, employer)
    return list(unique.values())


def configured_adapters(settings: Settings, user: User | None, db: Session, client=None) -> list[Adapter]:
    row = user_settings_row(db, user)
    overrides = source_overrides(row)
    adapters: list[Adapter] = []
    if settings.demo_mode:
        adapters.append(DemoCatalogAdapter())
    for employer in monitored_employers(settings, row):
        if overrides.get(employer.source_key) is False:
            continue
        adapter = adapter_for_employer(employer, client=client)
        if adapter:
            adapters.append(adapter)
    for key, meta in BOARD_SOURCES.items():
        source_key = f"board:{key}"
        enabled = overrides.get(source_key, meta["default"])
        if key == "adzuna":
            enabled = enabled and settings.adzuna_configured
        elif not settings.public_job_sources:
            enabled = False
        if not enabled:
            continue
        adapter = board_adapter(key, settings, client=client)
        if adapter:
            adapters.append(adapter)
    return adapters


def adapter_key(adapter: Adapter) -> str:
    if adapter.kind == "employer":
        return adapter.key
    if adapter.kind == "sample":
        return "sample"
    return f"board:{adapter.name}"


# ---------------------------------------------------------------------------
# Running a discovery
# ---------------------------------------------------------------------------


def _fetch(adapter: Adapter, plan: SearchPlan, http: Http) -> tuple[list[NormalizedJob], list[NormalizedJob]]:
    listings = adapter.fetch(plan, http)
    if adapter.kind == "sample":
        for job in listings:
            job.classify()
        return listings, listings
    kept = [job for job in listings if plan.accept(job)]
    return listings, kept


def run_discovery(
    db: Session,
    user: User,
    plan: SearchPlan,
    *,
    settings: Settings | None = None,
    client=None,
    task: BackgroundTask | None = None,
    commit_each: bool = False,
    max_workers: int = 10,
) -> dict:
    settings = settings or get_settings()
    adapters = configured_adapters(settings, user, db, client=client)
    progress = {
        adapter_key(adapter): {"label": adapter.label, "kind": adapter.kind, "status": "pending", "found": 0, "new": 0}
        for adapter in adapters
    }
    summary = {"created": 0, "updated": 0, "duplicates": 0, "expired": 0, "found": 0, "errors": [], "sources": [adapter.name for adapter in adapters]}
    touched: list[JobPosting] = []

    def save_progress() -> None:
        if task is None:
            return
        task.payload = dumps({"plan": _plan_summary(plan), "sources": progress, **{k: v for k, v in summary.items() if k != "sources"}})
        if commit_each:
            db.commit()

    if not adapters:
        summary["errors"].append(
            {"source": "none", "message": "No job sources are enabled. Turn sources on in Settings, or add an employer careers URL."}
        )
    save_progress()
    http = Http(client)
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(adapters) or 1))) as pool:
            futures = {pool.submit(_fetch, adapter, plan, http): adapter for adapter in adapters}
            for key in progress:
                progress[key]["status"] = "running"
            save_progress()
            for future in as_completed(futures):
                adapter = futures[future]
                key = adapter_key(adapter)
                try:
                    listings, kept = future.result()
                except ProviderError as exc:
                    progress[key].update(status="error", error=str(exc))
                    summary["errors"].append({"source": adapter.name, "label": adapter.label, "message": str(exc), "rate_limited": exc.rate_limited})
                    save_progress()
                    continue
                except Exception as exc:  # noqa: BLE001 - one broken feed must not stop the others
                    log.exception("Job source %s failed", key)
                    progress[key].update(status="error", error=f"Unexpected response ({exc.__class__.__name__}).")
                    summary["errors"].append({"source": adapter.name, "label": adapter.label, "message": "Unexpected response from this source.", "rate_limited": False})
                    save_progress()
                    continue
                new_here = 0
                for listing in kept:
                    try:
                        with db.begin_nested():
                            state, posting = upsert_posting(db, listing)
                    except Exception:  # noqa: BLE001 - one malformed posting must not stop the run
                        log.exception("Could not store a posting from %s", key)
                        continue
                    if state == "created":
                        summary["created"] += 1
                        new_here += 1
                    elif state == "updated":
                        summary["updated"] += 1
                    elif state == "duplicate":
                        summary["duplicates"] += 1
                    if posting is not None:
                        touched.append(posting)
                if adapter.full_catalog and adapter.listed_ids is not None:
                    summary["expired"] += _expire_missing(db, adapter, adapter.listed_ids)
                summary["found"] += len(kept)
                progress[key].update(status="done", found=len(kept), new=new_here, scanned=len(listings))
                save_progress()
    finally:
        http.close()
    summary["expired"] += expire_stale(db)
    profile = get_profile(db, user)
    summary["matched"] = refresh_matches(db, user, profile, postings=touched)
    summary["demo_mode"] = settings.demo_mode
    summary["progress"] = progress
    return summary


def _plan_summary(plan: SearchPlan) -> dict:
    return {"families": plan.families, "levels": plan.levels, "scopes": plan.scopes, "city": plan.city}


def sync_jobs(
    db: Session,
    user: User,
    query: SearchQuery | None = None,
    *,
    settings: Settings | None = None,
    client=None,
    profile: SearchProfile | None = None,
) -> dict:
    """Synchronous discovery for one search profile. Used by the API and tests."""
    from app.services.search_profiles import default_profile, plan_from_profile

    settings = settings or get_settings()
    profile = profile or default_profile(db, user)
    plan = plan_from_profile(profile, work_authorization=work_authorization(user_settings_row(db, user)))
    if query and query.keywords:
        plan.include_keywords = [query.keywords]
        plan.terms = [query.keywords, *plan.terms]
    if query and query.location:
        plan.city = query.location
    task = BackgroundTask(
        user_id=user.id,
        name="job_sync",
        status="running",
        payload=dumps({"plan": _plan_summary(plan)}),
        attempts=1,
        created_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.flush()
    summary = run_discovery(db, user, plan, settings=settings, client=client, task=task)
    db.add(
        JobSearch(
            user_id=user.id,
            query=dumps({"profile_id": profile.id, "keywords": query.keywords if query else "", **_plan_summary(plan)}),
            created_at=datetime.now(timezone.utc),
            result_count=summary["created"] + summary["updated"],
        )
    )
    profile.last_run_at = datetime.now(timezone.utc)
    task.status = "succeeded" if not summary["errors"] else "completed_with_errors"
    task.error = dumps(summary["errors"]) if summary["errors"] else None
    task.finished_at = datetime.now(timezone.utc)
    db.flush()
    summary["task_id"] = task.id
    return summary


# Background discovery ----------------------------------------------------------

_RUNNING: dict[str, threading.Thread] = {}


def start_background_discovery(user_id: str, profile_id: str | None, keywords: str = "") -> str:
    """Start discovery in a thread with its own session. Returns the task id to poll."""
    from app.core.database import SessionLocal
    from app.services.search_profiles import get_profile_for_user, plan_from_profile

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        profile = get_profile_for_user(db, user, profile_id)
        plan = plan_from_profile(profile, work_authorization=work_authorization(user_settings_row(db, user)))
        if keywords:
            plan.include_keywords = [keywords]
            plan.terms = [keywords, *plan.terms]
        task = BackgroundTask(
            user_id=user_id,
            name="job_discovery",
            status="running",
            payload=dumps({"plan": _plan_summary(plan), "profile_id": profile.id}),
            attempts=1,
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)
        db.commit()
        task_id = task.id
        profile_key = profile.id
    finally:
        db.close()

    def work() -> None:
        session = SessionLocal()
        try:
            user = session.get(User, user_id)
            task = session.get(BackgroundTask, task_id)
            profile = session.get(SearchProfile, profile_key)
            summary = run_discovery(session, user, plan, task=task, commit_each=True)
            if profile:
                profile.last_run_at = datetime.now(timezone.utc)
            session.add(
                JobSearch(
                    user_id=user_id,
                    query=dumps({"profile_id": profile_key, "keywords": keywords, **_plan_summary(plan)}),
                    created_at=datetime.now(timezone.utc),
                    result_count=summary["created"] + summary["updated"],
                )
            )
            task.status = "succeeded" if not summary["errors"] else "completed_with_errors"
            task.error = dumps(summary["errors"]) if summary["errors"] else None
            task.payload = dumps({**loads(task.payload, {}), **{k: v for k, v in summary.items() if k not in {"progress", "sources"}}, "sources": summary["progress"], "done": True})
            task.finished_at = datetime.now(timezone.utc)
            session.commit()
        except Exception as exc:  # noqa: BLE001
            log.exception("Background discovery failed")
            session.rollback()
            task = session.get(BackgroundTask, task_id)
            if task:
                task.status = "failed"
                task.error = dumps([{"source": "discovery", "message": f"Discovery stopped: {exc.__class__.__name__}"}])
                task.finished_at = datetime.now(timezone.utc)
                session.commit()
        finally:
            session.close()
            _RUNNING.pop(task_id, None)

    thread = threading.Thread(target=work, name=f"discovery-{task_id[:8]}", daemon=True)
    _RUNNING[task_id] = thread
    thread.start()
    return task_id


def discovery_status(db: Session, user: User, task_id: str) -> dict | None:
    task = db.get(BackgroundTask, task_id)
    if task is None or task.user_id != user.id:
        return None
    db.refresh(task)
    payload = loads(task.payload, {})
    return {
        "id": task.id,
        "status": task.status,
        "done": task.status != "running",
        "created": payload.get("created", 0),
        "updated": payload.get("updated", 0),
        "duplicates": payload.get("duplicates", 0),
        "expired": payload.get("expired", 0),
        "found": payload.get("found", 0),
        "sources": payload.get("sources", {}),
        "errors": loads(task.error, []) if task.error else payload.get("errors", []),
        "started_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


def latest_discovery(db: Session, user: User) -> dict | None:
    task = db.scalar(
        select(BackgroundTask)
        .where(BackgroundTask.user_id == user.id, BackgroundTask.name.in_(["job_discovery", "job_sync"]))
        .order_by(BackgroundTask.created_at.desc())
    )
    return discovery_status(db, user, task.id) if task else None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _apply_classification(posting: JobPosting, listing: NormalizedJob) -> None:
    posting.role_family = listing.role_family
    posting.role_families = dumps(listing.role_families)
    posting.location_scope = listing.location_scope
    posting.experience_years = listing.experience_years
    posting.level_reason = listing.level_reason
    posting.seniority = listing.seniority
    posting.source_label = listing.source_label or SOURCE_NAMES.get(listing.source, listing.source)
    posting.employer_key = listing.employer_key
    posting.expires_at = listing.expires_at
    posting.needs_detail = bool(listing.raw.get("needs_detail"))


def upsert_posting(db: Session, listing: NormalizedJob) -> tuple[str, JobPosting | None]:
    if not listing.role_families and listing.seniority is None:
        listing.classify()
    now = datetime.now(timezone.utc)
    existing = db.scalar(
        select(JobPosting).where(JobPosting.source == listing.source, JobPosting.external_id == listing.external_id)
    )
    if existing is None:
        key = listing.fingerprint
        duplicate = db.scalar(
            select(JobPosting).where(JobPosting.fingerprint == key, JobPosting.is_sample.is_(listing.is_sample))
        )
        if duplicate is not None:
            _merge_duplicate(duplicate, listing, now)
            return "duplicate", duplicate
        posting = JobPosting(
            source=listing.source,
            external_id=listing.external_id,
            fingerprint=key,
            title=listing.title[:300],
            company=listing.company[:240],
            industry=listing.industry,
            location=(listing.location or None) and listing.location[:240],
            work_arrangement=listing.work_arrangement,
            employment_type=listing.employment_type,
            seniority=listing.seniority,
            salary_min=listing.salary_min,
            salary_max=listing.salary_max,
            salary_currency=listing.salary_currency,
            description=listing.description,
            application_url=listing.application_url,
            posted_at=listing.posted_at,
            discovered_at=now,
            last_verified_at=now,
            is_active=True,
            is_sample=listing.is_sample,
            raw_payload=dumps(listing.raw),
            also_seen_on="[]",
        )
        _apply_classification(posting, listing)
        db.add(posting)
        db.flush()
        _replace_analysis(db, posting)
        return "created", posting
    changed = existing.description != listing.description or existing.title != listing.title
    existing.last_verified_at = now
    existing.is_active = True
    existing.employment_type = listing.employment_type if listing.employment_type not in {None, "", "unknown"} else existing.employment_type
    existing.application_url = listing.application_url or existing.application_url
    existing.location = ((listing.location or None) and listing.location[:240]) or existing.location
    existing.posted_at = existing.posted_at or listing.posted_at
    keep_detail = existing.needs_detail is False and len(existing.description or "") > len(listing.description or "")
    _apply_classification(existing, listing)
    if keep_detail:
        existing.needs_detail = False
    if changed and not keep_detail:
        existing.description = listing.description
        existing.title = listing.title[:300]
        _replace_analysis(db, existing)
        return "updated", existing
    return "unchanged", existing


def _merge_duplicate(posting: JobPosting, listing: NormalizedJob, now: datetime) -> None:
    posting.last_verified_at = now
    posting.is_active = True
    seen = loads(posting.also_seen_on, [])
    entry = {"source": listing.source, "label": listing.source_label or SOURCE_NAMES.get(listing.source, listing.source), "url": listing.application_url}
    if SOURCE_PRIORITY.get(listing.source, 1) > SOURCE_PRIORITY.get(posting.source, 1) and listing.application_url:
        # Prefer the employer's own posting and keep the aggregator as a secondary link.
        seen.append({"source": posting.source, "label": posting.source_label or SOURCE_NAMES.get(posting.source, posting.source), "url": posting.application_url})
        posting.source = listing.source
        posting.external_id = listing.external_id
        posting.application_url = listing.application_url
        posting.source_label = listing.source_label
        posting.employer_key = listing.employer_key
        if len(listing.description or "") > len(posting.description or ""):
            posting.description = listing.description
            posting.needs_detail = False
        posting.posted_at = posting.posted_at or listing.posted_at
        posting.expires_at = listing.expires_at or posting.expires_at
    elif not any(item.get("url") == entry["url"] for item in seen) and entry["url"] != posting.application_url:
        seen.append(entry)
    posting.also_seen_on = dumps(seen[-6:])


def _expire_missing(db: Session, adapter: Adapter, listed_ids: set[str]) -> int:
    """For boards that list every open job, a posting that disappears has closed."""
    prefix = f"{adapter.employer.board}:" if hasattr(adapter, "employer") else ""
    rows = db.scalars(
        select(JobPosting).where(JobPosting.source == adapter.name, JobPosting.is_active.is_(True), JobPosting.external_id.like(f"{prefix}%"))
    ).all()
    expired = 0
    for row in rows:
        if row.external_id not in listed_ids:
            row.is_active = False
            expired += 1
    return expired


def expire_stale(db: Session) -> int:
    now = datetime.now(timezone.utc)
    expired = 0
    rows = db.scalars(select(JobPosting).where(JobPosting.is_active.is_(True), JobPosting.expires_at.is_not(None))).all()
    for row in rows:
        if ensure_utc(row.expires_at) < now:
            row.is_active = False
            expired += 1
    return expired


def _replace_analysis(db: Session, posting: JobPosting) -> None:
    for requirement in list(posting.requirements):
        db.delete(requirement)
    db.flush()
    analysis = analyze_job_text(posting.title, posting.description)
    if posting.seniority is None:
        posting.seniority = analysis["seniority"]
    if posting.work_arrangement in {"", "unknown"}:
        posting.work_arrangement = analysis["work_arrangement"]
    if posting.employment_type in {"", "unknown"}:
        posting.employment_type = analysis["employment_type"]
    posting.responsibilities = analysis["responsibilities"]
    for item in analysis["requirements"]:
        db.add(
            JobRequirement(
                job_posting_id=posting.id,
                name=item["name"][:200],
                normalized_name=item["normalized_name"][:200],
                category=item["category"],
                priority=item["priority"],
                raw_text=item["raw_text"],
                min_years=item["min_years"],
                is_ambiguous=item["is_ambiguous"],
            )
        )
    db.flush()
    db.expire(posting, ["requirements"])


def reanalyze(db: Session, posting: JobPosting) -> None:
    _replace_analysis(db, posting)


def backfill_classification(db: Session) -> int:
    """Classify postings stored before relevance fields existed."""
    rows = db.scalars(select(JobPosting).where(JobPosting.role_families.is_(None))).all()
    for row in rows:
        listing = NormalizedJob(
            source=row.source,
            external_id=row.external_id,
            title=row.title,
            company=row.company,
            description=row.description or "",
            location=row.location,
            work_arrangement=row.work_arrangement or "unknown",
            employment_type=row.employment_type or "unknown",
            is_sample=row.is_sample,
            remote_flag=True if row.work_arrangement == "remote" else None,
        ).classify()
        if row.is_sample:
            listing.seniority = row.seniority or listing.seniority
        _apply_classification(row, listing)
        row.fingerprint = fingerprint(row.company, row.title, row.location)
        row.also_seen_on = row.also_seen_on or "[]"
    db.flush()
    return len(rows)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _match_candidates(db: Session, user: User):
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    stmt = select(JobPosting).where(
        JobPosting.is_active.is_(True),
        or_(JobPosting.user_id.is_(None), JobPosting.user_id == user.id),
        or_(JobPosting.posted_at.is_(None), JobPosting.posted_at >= cutoff),
    )
    if not get_settings().demo_mode:
        stmt = stmt.where(JobPosting.is_sample.is_(False))
    return db.scalars(stmt).all()


def refresh_matches(db: Session, user: User, profile: Profile | None = None, postings: list[JobPosting] | None = None) -> int:
    profile = profile or get_profile(db, user)
    rows = postings if postings is not None else _match_candidates(db, user)
    count = 0
    seen: set[str] = set()
    for posting in rows:
        if posting.id in seen:
            continue
        seen.add(posting.id)
        if posting.user_id not in {None, user.id}:
            continue
        if not get_settings().demo_mode and posting.is_sample:
            continue
        _write_match(db, user, profile, posting)
        count += 1
    return count


def _write_match(db: Session, user: User, profile: Profile, posting: JobPosting) -> JobMatch:
    assessment = build_assessment(profile, posting)
    match = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_posting_id == posting.id))
    if match is None:
        match = JobMatch(user_id=user.id, job_posting_id=posting.id)
        db.add(match)
    latest = profile.versions[-1] if profile.versions else None
    match.profile_version_id = latest.id if latest else None
    match.qualification_score = assessment["qualification_score"]
    match.career_interest_score = assessment["career_interest_score"]
    match.explanation = dumps(assessment)
    db.flush()
    return match


def queue_verification_for_job(db: Session, user: User, profile: Profile, posting: JobPosting) -> None:
    """Ask about undocumented skills only for a job the user is preparing to apply to."""
    _ensure_verification_requests(db, user, profile, posting)


def _ensure_verification_requests(db: Session, user: User, profile: Profile, posting: JobPosting) -> None:
    for requirement in posting.requirements:
        if not needs_verification(profile, requirement):
            continue
        open_request = db.scalar(
            select(QualificationVerificationRequest).where(
                QualificationVerificationRequest.user_id == user.id,
                QualificationVerificationRequest.normalized_name == requirement.normalized_name,
                QualificationVerificationRequest.status == "open",
            )
        )
        if open_request:
            if open_request.job_posting_id != posting.id:
                # Keep one question per skill, but show it for the job the user is working on now.
                open_request.job_posting_id = posting.id
                open_request.prompt = verification_prompt(requirement, already_confirmed=False, job_title=posting.title)
            continue
        row = next(
            (item for item in profile.profile_skills if item.skill.normalized_name == requirement.normalized_name),
            None,
        )
        db.add(
            QualificationVerificationRequest(
                user_id=user.id,
                job_posting_id=posting.id,
                normalized_name=requirement.normalized_name,
                display_name=requirement.name,
                prompt=verification_prompt(requirement, already_confirmed=row is not None, job_title=posting.title),
                priority=requirement.priority,
                min_years=requirement.min_years,
                status="open",
                created_at=datetime.now(timezone.utc),
            )
        )
    db.flush()


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


def run_due_schedules(db: Session, settings: Settings | None = None) -> dict:
    now = datetime.now(timezone.utc)
    ran = 0
    schedules = db.scalars(select(JobSearchSchedule).where(JobSearchSchedule.enabled.is_(True))).all()
    for schedule in schedules:
        if schedule.next_run_at and ensure_utc(schedule.next_run_at) > now:
            continue
        user = db.get(User, schedule.user_id)
        if user is None:
            continue
        payload = loads(schedule.query, {})
        try:
            sync_jobs(db, user, SearchQuery(keywords=payload.get("keywords", ""), location=payload.get("location", "")), settings=settings)
        except ProviderError:
            pass
        schedule.last_run_at = now
        schedule.next_run_at = now + timedelta(minutes=max(schedule.interval_minutes, 60))
        ran += 1
    # Saved search profiles with auto-refresh on.
    profiles = db.scalars(select(SearchProfile).where(SearchProfile.auto_refresh.is_(True), SearchProfile.is_default.is_(True))).all()
    for profile in profiles:
        if profile.last_run_at and ensure_utc(profile.last_run_at) > now - timedelta(hours=profile.refresh_hours or 24):
            continue
        user = db.get(User, profile.user_id)
        if user is None:
            continue
        sync_jobs(db, user, None, settings=settings, profile=profile)
        ran += 1
    return {"ran": ran}


def record_provider_failure(db: Session, user_id: str | None, message: str, *, rate_limited: bool) -> BackgroundTask:
    task = BackgroundTask(
        user_id=user_id,
        name="job_source",
        status="rate_limited" if rate_limited else "failed",
        payload="{}",
        error=message[:500],
        attempts=1,
        created_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.flush()
    return task


# ---------------------------------------------------------------------------
# Manual and imported postings
# ---------------------------------------------------------------------------


def manual_posting(
    db: Session,
    user: User,
    *,
    title: str,
    company: str,
    description: str,
    location: str | None,
    application_url: str | None,
    source: str = "manual",
    posted_at: datetime | None = None,
    expires_at: datetime | None = None,
    source_label: str | None = None,
) -> JobPosting:
    from app.services.analysis import detect_arrangement, detect_employment

    listing = NormalizedJob(
        source=source,
        external_id=f"{user.id}:{int(datetime.now().timestamp() * 1000)}:{title[:40]}",
        title=title.strip(),
        company=company.strip(),
        description=description.strip(),
        location=location,
        application_url=application_url,
        posted_at=posted_at,
        expires_at=expires_at,
        source_label=source_label or SOURCE_NAMES.get(source),
    )
    listing.work_arrangement = detect_arrangement(title, f"{location or ''} {description[:800]}")
    listing.employment_type = detect_employment(title, description[:800])
    listing.classify()
    state, posting = upsert_posting(db, listing)
    if posting is None:
        raise RuntimeError(f"Manual posting was not stored ({state}).")
    if posting.user_id is None and posting.source in {"manual", "import"}:
        posting.user_id = user.id
    refresh_matches(db, user, postings=[posting])
    return posting


def posting_visible(posting: JobPosting, user: User, settings: Settings) -> bool:
    if posting.user_id not in {None, user.id}:
        return False
    if posting.is_sample and not settings.demo_mode:
        return False
    return True


def load_match(db: Session, user: User, posting: JobPosting) -> dict:
    profile = get_profile(db, user)
    match = _write_match(db, user, profile, posting)
    return json.loads(match.explanation)
