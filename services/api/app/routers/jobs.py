from datetime import datetime, timezone

import re

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import JobPosting, JobSearchSchedule, QualificationVerificationRequest, SavedJob, SearchProfile, User
from app.routers.common import error, not_found, page
from app.services import search_profiles as profiles_service
from app.services.employers import EMPLOYERS, employer_to_dict, parse_careers_url
from app.services.http_fetch import Http, ProviderError
from app.services.job_enrich import ImportNeedsText, enrich_posting, fetch_posting_from_url, restricted_platform
from app.services.job_search import JobFilters, external_searches, job_card, search_jobs
from app.services.job_sources import BOARD_SOURCES, SearchPlan, SearchQuery, adapter_for_employer
from app.services.job_sync import (
    backfill_classification,
    discovery_status,
    latest_discovery,
    load_match,
    manual_posting,
    monitored_employers,
    posting_visible,
    refresh_matches,
    run_due_schedules,
    source_overrides,
    start_background_discovery,
    sync_jobs,
    user_settings_row,
)
from app.services.jsonutil import dumps, loads
from app.services.profile_ops import get_profile, snapshot_profile, upsert_profile_skill

router = APIRouter(prefix="/api/v1", tags=["jobs"])


class SyncIn(BaseModel):
    keywords: str = ""
    location: str = ""
    profile_id: str | None = None


class ManualJobIn(BaseModel):
    title: str
    company: str
    description: str = Field(min_length=20)
    location: str | None = None
    application_url: str | None = None


class ImportIn(BaseModel):
    url: str | None = None
    title: str | None = None
    company: str | None = None
    description: str | None = None
    location: str | None = None


class CaptureIn(BaseModel):
    portal: str  # york, linkedin, or web (one link)
    url: str | None = None
    term: str | None = None


class EmployerLinkIn(BaseModel):
    url: str = Field(min_length=8, max_length=800)


class ScheduleIn(BaseModel):
    keywords: str = ""
    location: str = ""
    interval_minutes: int = 1440
    enabled: bool = True


class AnswerIn(BaseModel):
    request_id: str | None = None
    normalized_name: str
    choice: str
    context: str | None = None
    setting: str | None = None
    accomplishment: str | None = None
    proficiency: str | None = None
    duration_months: int | None = None
    project_id: str | None = None
    experience_id: str | None = None


class AnswerBatch(BaseModel):
    answers: list[AnswerIn]
    job_id: str | None = None


class SourcesIn(BaseModel):
    overrides: dict[str, bool] = Field(default_factory=dict)


class EmployerIn(BaseModel):
    url: str
    name: str | None = None


class ProfileIn(BaseModel):
    name: str | None = None
    role_families: list[str] | None = None
    custom_titles: list[str] | None = None
    levels: list[str] | None = None
    location_scopes: list[str] | None = None
    city: str | None = None
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    exclude_companies: list[str] | None = None
    employment_types: list[str] | None = None
    work_arrangements: list[str] | None = None
    posted_within_days: int | None = None
    auto_refresh: bool | None = None
    refresh_hours: int | None = None


# ---------------------------------------------------------------------------
# Search profiles
# ---------------------------------------------------------------------------


@router.get("/search-profiles/options")
def profile_options(user: User = Depends(get_current_user)):
    return profiles_service.options()


@router.get("/search-profiles")
def list_search_profiles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = profiles_service.list_profiles(db, user)
    db.commit()
    return [profiles_service.serialize(row) for row in rows]


@router.post("/search-profiles", status_code=201)
def create_search_profile(payload: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    base = profiles_service.default_profile(db, user)
    row = SearchProfile(
        user_id=user.id,
        name="New search",
        is_default=False,
        role_families=base.role_families,
        levels=base.levels,
        location_scopes=base.location_scopes,
        city=base.city,
        custom_titles="[]",
        include_keywords="[]",
        exclude_keywords=base.exclude_keywords,
        exclude_companies=base.exclude_companies,
        employment_types="[]",
        work_arrangements="[]",
        posted_within_days=base.posted_within_days,
        auto_refresh=False,
        refresh_hours=24,
    )
    profiles_service.apply_payload(row, payload.model_dump(exclude_unset=True))
    db.add(row)
    db.commit()
    return profiles_service.serialize(row)


@router.put("/search-profiles/{profile_id}")
def update_search_profile(profile_id: str, payload: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(SearchProfile, profile_id)
    if row is None or row.user_id != user.id:
        raise not_found()
    profiles_service.apply_payload(row, payload.model_dump(exclude_unset=True))
    db.commit()
    return profiles_service.serialize(row)


@router.post("/search-profiles/{profile_id}/default")
def make_default(profile_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(SearchProfile, profile_id)
    if row is None or row.user_id != user.id:
        raise not_found()
    profiles_service.set_default(db, user, row)
    db.commit()
    return profiles_service.serialize(row)


@router.delete("/search-profiles/{profile_id}")
def delete_search_profile(profile_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(SearchProfile, profile_id)
    if row is None or row.user_id != user.id:
        raise not_found()
    rows = profiles_service.list_profiles(db, user)
    if len(rows) <= 1:
        raise error(409, "last_profile", "Keep at least one search profile.")
    was_default = row.is_default
    db.delete(row)
    db.flush()
    if was_default:
        remaining = profiles_service.list_profiles(db, user)
        profiles_service.set_default(db, user, remaining[0])
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@router.post("/jobs/sync")
def sync(payload: SyncIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Run discovery now and wait for it. The web app uses /jobs/discover instead."""
    backfill_classification(db)
    profile = profiles_service.get_profile_for_user(db, user, payload.profile_id)
    result = sync_jobs(db, user, SearchQuery(keywords=payload.keywords, location=payload.location), profile=profile)
    db.commit()
    result.pop("progress", None)
    return result


@router.post("/jobs/discover", status_code=202)
def discover(payload: SyncIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    backfill_classification(db)
    profile = profiles_service.get_profile_for_user(db, user, payload.profile_id)
    db.commit()
    task_id = start_background_discovery(user.id, profile.id, payload.keywords)
    return {"task_id": task_id}


@router.get("/jobs/discover/latest")
def discover_latest(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return latest_discovery(db, user) or {}


@router.get("/jobs/discover/{task_id}")
def discover_status(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    status = discovery_status(db, user, task_id)
    if status is None:
        raise not_found()
    return status


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@router.get("/jobs")
def list_jobs(
    q: str = "",
    location: str = "",
    company: str = "",
    industry: str = "",
    employment_type: str = "",
    seniority: str = "",
    work_arrangement: str = "",
    source: str = "",
    min_salary: int | None = None,
    min_qualification: int | None = None,
    min_interest: int | None = None,
    saved: bool = False,
    include_samples: bool = True,
    include_dismissed: bool = False,
    profile_id: str | None = None,
    use_profile: bool = False,
    families: str | None = None,
    levels: str | None = None,
    scopes: str | None = None,
    posted_within_days: int | None = None,
    sort: str = "relevance",
    ids: str | None = None,
    page_number: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if ids:
        wanted = _csv(ids)[:50]
        result = search_jobs(db, user, JobFilters(include_samples=True, include_dismissed=True))
        by_id = {item["id"]: item for item in result["items"]}
        items = [by_id[job_id] for job_id in wanted if job_id in by_id]
        return {"items": items, "total": len(items), "page": 1, "page_size": len(items), "facets": {}, "hidden": result["hidden"]}
    if profile_id or use_profile:
        filters = JobFilters.from_profile(profiles_service.get_profile_for_user(db, user, profile_id))
    else:
        filters = JobFilters()
    if families is not None:
        filters.families = _csv(families)
    if levels is not None:
        filters.levels = _csv(levels)
    if scopes is not None:
        filters.scopes = _csv(scopes)
    if posted_within_days is not None:
        filters.posted_within_days = posted_within_days or None
    filters.q = q
    filters.company = company
    filters.source = source
    filters.location = location
    filters.industry = industry
    filters.seniority = seniority
    filters.employment_type = employment_type
    filters.work_arrangement = work_arrangement
    filters.min_salary = min_salary
    filters.min_qualification = min_qualification
    filters.min_interest = min_interest
    filters.saved_only = saved
    filters.include_samples = include_samples
    filters.include_dismissed = include_dismissed
    filters.sort = sort
    result = search_jobs(db, user, filters)
    payload = page(result["items"], page_number, page_size)
    payload["facets"] = result["facets"]
    payload["hidden"] = result["hidden"]
    return payload


@router.get("/jobs/sources")
def sources(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    row = user_settings_row(db, user)
    overrides = source_overrides(row)
    employers = []
    custom_keys = {item.get("key") for item in loads(row.custom_employers, [])} if row else set()
    for employer in monitored_employers(settings, row):
        key = employer.source_key
        employers.append(
            {
                **employer_to_dict(employer),
                "source_key": key,
                "enabled": overrides.get(key, True),
                "custom": employer.key in custom_keys,
            }
        )
    boards = []
    for key, meta in BOARD_SOURCES.items():
        source_key = f"board:{key}"
        configured = settings.adzuna_configured if key == "adzuna" else settings.public_job_sources
        boards.append(
            {
                "key": key,
                "source_key": source_key,
                "label": meta["label"],
                "description": meta["description"],
                "enabled": overrides.get(source_key, meta["default"]) and configured,
                "configured": configured,
                "needs_key": bool(meta.get("needs_key")) and not configured,
            }
        )
    profile = profiles_service.default_profile(db, user)
    db.commit()
    return {
        "demo_mode": settings.demo_mode,
        "sample_catalog": settings.demo_mode,
        "public_sources": [board["key"] for board in boards if board["enabled"]],
        "adzuna": settings.adzuna_configured,
        "boards": boards,
        "employers": employers,
        "external_searches": external_searches(profile),
        "live_submission": [],
        "submission_methods": ["simulated", "manual"],
        "note": "Every source here is a public listing API or feed. Listing access does not grant application submission. LinkedIn, Indeed, and university portals are reached through saved searches and import.",
    }


@router.put("/jobs/sources")
def update_sources(payload: SourcesIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = user_settings_row(db, user)
    overrides = source_overrides(row)
    overrides.update({key: bool(value) for key, value in payload.overrides.items()})
    row.disabled_sources = dumps(overrides)
    db.commit()
    return {"overrides": overrides}


@router.post("/jobs/sources/employers", status_code=201)
def add_employer(payload: EmployerIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    employer = parse_careers_url(payload.url, payload.name)
    if employer is None:
        platform = restricted_platform(payload.url)
        if platform:
            raise error(400, "restricted_platform", f"{platform} cannot be monitored automatically. Use saved searches and import postings instead.")
        raise error(
            400,
            "unsupported_careers_site",
            "ApplyPilot can monitor careers sites hosted on Workday, Greenhouse, Lever, or Ashby. Paste a URL like https://company.wd3.myworkdayjobs.com/Careers or https://jobs.lever.co/company.",
        )
    adapter = adapter_for_employer(employer)
    try:
        with Http() as http:
            adapter.fetch(SearchPlan(families=[], levels=[], scopes=[], permissive=True, detail_cap=0), http)
    except ProviderError as exc:
        raise error(400, "careers_site_unreachable", f"That careers site did not respond as expected: {exc}") from exc
    row = user_settings_row(db, user)
    custom = [item for item in loads(row.custom_employers, []) if item.get("key") != employer.key]
    custom.append(employer_to_dict(employer))
    row.custom_employers = dumps(custom)
    db.commit()
    return {**employer_to_dict(employer), "source_key": employer.source_key, "enabled": True, "custom": True}


@router.delete("/jobs/sources/employers/{key}")
def remove_employer(key: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = user_settings_row(db, user)
    custom = [item for item in loads(row.custom_employers, []) if item.get("key") != key]
    row.custom_employers = dumps(custom)
    db.commit()
    return {"ok": True}


@router.get("/jobs/external-searches")
def saved_searches(profile_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = profiles_service.get_profile_for_user(db, user, profile_id)
    db.commit()
    return external_searches(profile)


@router.post("/jobs/manual", status_code=201)
def create_manual(payload: ManualJobIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    posting = manual_posting(
        db,
        user,
        title=payload.title,
        company=payload.company,
        description=payload.description,
        location=payload.location,
        application_url=payload.application_url,
    )
    db.commit()
    return {"id": posting.id}


@router.post("/jobs/import", status_code=201)
def import_job(payload: ImportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add a posting from a URL (read through a public API or structured data) or from pasted text."""
    fields: dict = {}
    if payload.url and not (payload.description and len(payload.description.strip()) >= 80):
        try:
            fields = fetch_posting_from_url(payload.url)
        except ImportNeedsText as exc:
            raise error(422, "paste_required", str(exc)) from exc
        except ProviderError as exc:
            raise error(422, "paste_required", f"The page could not be read ({exc}). Paste the job description instead.") from exc
    description = (payload.description or fields.get("description") or "").strip()
    title = (payload.title or fields.get("title") or "").strip()
    company = (payload.company or fields.get("company") or "").strip()
    if len(description) < 40:
        raise error(422, "description_required", "Paste the job description so it can be analyzed.")
    if not title:
        first_line = next((line.strip() for line in description.splitlines() if line.strip()), "")
        title = first_line[:120] or "Imported role"
    posting = manual_posting(
        db,
        user,
        title=title,
        company=company or "Company not listed",
        description=description,
        location=payload.location or fields.get("location"),
        application_url=payload.url or fields.get("url"),
        source="import",
        posted_at=fields.get("posted_at"),
        expires_at=fields.get("expires_at"),
        source_label=(f"Imported from {restricted_platform(payload.url)}" if payload.url and restricted_platform(payload.url) else fields.get("source_label")),
    )
    db.commit()
    return {"id": posting.id, "title": posting.title, "company": posting.company}


# ---------------------------------------------------------------------------
# Experience York and LinkedIn, through the ApplyPilot browser window
# ---------------------------------------------------------------------------


def _runner():
    from app.services.autoapply.runner import RUNNER

    return RUNNER


@router.get("/jobs/capture")
def capture_status(user: User = Depends(get_current_user)):
    return _runner().capture_status(user.id)


@router.post("/jobs/capture/start", status_code=202)
def capture_start(payload: CaptureIn, user: User = Depends(get_current_user)):
    if payload.portal not in {"york", "linkedin", "web"}:
        raise error(400, "invalid_portal", "Choose Experience York, LinkedIn, or a link.")
    url = (payload.url or "").strip() or None
    if url and not url.startswith("http"):
        url = "https://" + url
    if payload.portal == "web" and not url:
        raise error(400, "url_required", "Paste the posting's link.")
    if payload.portal == "york" or (url and re.search(r"yorku\.ca|orbissites\.com", url, re.I)):
        # Experience York blocks software-controlled browsers (Cloudflare). ApplyPilot respects that.
        raise error(400, "york_blocked", YORK_BLOCKED)
    _runner().send("capture_start", None, {"user_id": user.id, "portal": payload.portal, "url": url, "term": (payload.term or "").strip()[:60] or None})
    return {"started": True}


@router.post("/jobs/capture/read-list", status_code=202)
def capture_read_list(payload: CaptureIn, user: User = Depends(get_current_user)):
    _runner().send("capture_read_list", None, {"user_id": user.id, "term": (payload.term or "").strip()[:60] or None})
    return {"started": True}


@router.post("/jobs/capture/stop")
def capture_stop(user: User = Depends(get_current_user)):
    _runner().send("capture_stop", None, {"user_id": user.id})
    return {"stopped": True}


YORK_BLOCKED = (
    "Experience York blocks browsers that are controlled by software, so ApplyPilot does not open it. "
    "Use the Save to ApplyPilot bookmark in your usual browser, or import saved pages, on the York co-op page."
)


class YorkPageIn(BaseModel):
    html: str | None = Field(default=None, max_length=6_000_000)
    text: str | None = Field(default=None, max_length=500_000)
    url: str | None = Field(default=None, max_length=2000)


class YorkSettingsIn(BaseModel):
    ai_permission: bool


def _york_settings(db: Session, user: User) -> dict:
    from app.services.privacy import york_permission

    return {"ai_permission": york_permission(db, user.id)}


@router.get("/jobs/york")
def york_postings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Your saved Experience York postings, ranked against your profile and projects. Computed here, without AI."""
    from app.services import york

    result = york.ranking(db, user)
    db.commit()
    return {**result, **_york_settings(db, user)}


@router.post("/jobs/york/import")
def york_import(payload: YorkPageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A page you sent from your own browser with the Save to ApplyPilot bookmark: a posting or a posting list."""
    from app.services import york

    if not (payload.html or payload.text):
        raise error(400, "empty", "Nothing was sent.")
    result = york.import_page(db, user, html=payload.html or "", text=payload.text or "", url=payload.url or "")
    db.commit()
    return result


@router.post("/jobs/york/files")
async def york_files(files: list[UploadFile] = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pages you saved from Experience York (Save Page As, or Print > Save as PDF). Parsed here, without AI."""
    from app.services import york

    results = []
    for upload in files[:200]:
        data = await upload.read()
        name = upload.filename or "page"
        if len(data) > 15_000_000:
            results.append({"file": name, "kind": "error", "message": "The file is too large."})
            continue
        try:
            if name.lower().endswith(".pdf") or data[:5] == b"%PDF-":
                import pymupdf

                with pymupdf.open(stream=data, filetype="pdf") as pdf:
                    text = "\n".join(page.get_text() for page in pdf)
                result = york.import_page(db, user, text=text)
            elif name.lower().endswith((".html", ".htm", ".mhtml")) or b"<html" in data[:4000].lower():
                result = york.import_page(db, user, html=data.decode("utf-8", errors="replace"))
            else:
                result = york.import_page(db, user, text=data.decode("utf-8", errors="replace"))
            db.commit()
        except Exception as exc:  # noqa: BLE001 - one unreadable file does not stop the rest
            db.rollback()
            result = {"kind": "error", "message": f"Could not read this file ({exc.__class__.__name__})."}
        results.append({"file": name, **result})
    return {"results": results, "saved": sum(len(item.get("saved") or []) for item in results)}


@router.put("/jobs/york/settings")
def york_settings(payload: YorkSettingsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Only turn this on if York has told you that you may process co-op postings with an outside AI service."""
    row = user_settings_row(db, user)
    if row is None:
        from app.models import UserSettings

        row = UserSettings(user_id=user.id)
        db.add(row)
    row.york_ai_permission = payload.ai_permission
    db.commit()
    return _york_settings(db, user)


def portal_details(db: Session, user: User, posting: JobPosting) -> list[dict]:
    from app.models import PortalPosting
    from app.services.capture import PORTALS, channels

    rows = db.scalars(select(PortalPosting).where(PortalPosting.user_id == user.id, PortalPosting.job_posting_id == posting.id)).all()
    return [
        {
            "portal": row.portal, "name": PORTALS.get(row.portal, {}).get("name", row.portal), "url": row.url, "external_id": row.external_id,
            "application_method": row.application_method, "employer_url": row.employer_url, "deadline": row.deadline,
            "documents": row.documents, "term": row.term, "easy_apply": row.easy_apply, "channels": channels(row, posting),
        }
        for row in rows
    ]


@router.put("/jobs/{job_id}/employer-link")
def set_employer_link(job_id: str, payload: EmployerLinkIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The employer's own application page for a posting saved from Experience York or LinkedIn."""
    from app.models import PortalPosting
    from app.services.capture import set_employer_url

    posting = _get_job(db, user, job_id, include_inactive=True)
    url = payload.url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    rows = db.scalars(select(PortalPosting).where(PortalPosting.user_id == user.id, PortalPosting.job_posting_id == posting.id)).all()
    if not rows:
        raise error(400, "not_portal", "Only postings saved from Experience York or LinkedIn take a separate employer link.")
    for row in rows:
        set_employer_url(db, user.id, row.portal, row.external_id, url)
    db.commit()
    return {"application_url": posting.application_url, "portals": portal_details(db, user, posting)}


@router.post("/jobs/schedules", status_code=201)
def create_schedule(payload: ScheduleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    interval = max(payload.interval_minutes, 60)
    schedule = JobSearchSchedule(
        user_id=user.id,
        query=dumps({"keywords": payload.keywords, "location": payload.location}),
        interval_minutes=interval,
        enabled=payload.enabled,
        next_run_at=datetime.now(timezone.utc),
    )
    db.add(schedule)
    db.commit()
    return {"id": schedule.id, "interval_minutes": interval}


@router.post("/jobs/schedules/run-due")
def run_schedules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = run_due_schedules(db)
    db.commit()
    return result


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, refresh: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    posting = _get_job(db, user, job_id, include_inactive=True)
    verification = None
    if posting.is_active and (refresh or posting.needs_detail or len(posting.description or "") < 400):
        verification = enrich_posting(db, posting, force=refresh)
    match = load_match(db, user, posting)
    db.commit()
    saved_row = db.scalar(select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_posting_id == posting.id))
    saved = saved_row is not None and (saved_row.status or "saved") == "saved"
    card = job_card(posting, match["qualification_score"], match["career_interest_score"], match, saved)
    return {
        **card,
        "dismissed": saved_row is not None and saved_row.status == "dismissed",
        "description": posting.description,
        "responsibilities": posting.responsibilities,
        "match": match,
        "verification": verification,
        "portals": portal_details(db, user, posting),
    }


@router.post("/jobs/{job_id}/verify")
def verify_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    posting = _get_job(db, user, job_id, include_inactive=True)
    result = enrich_posting(db, posting, force=True)
    refresh_matches(db, user, postings=[posting])
    db.commit()
    return {**result, "is_active": posting.is_active}


def _set_saved(db: Session, user: User, posting: JobPosting, status: str | None) -> None:
    existing = db.scalar(select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_posting_id == posting.id))
    if status is None:
        if existing:
            db.delete(existing)
    elif existing is None:
        db.add(SavedJob(user_id=user.id, job_posting_id=posting.id, created_at=datetime.now(timezone.utc), status=status))
    else:
        existing.status = status
    db.commit()


@router.post("/jobs/{job_id}/save")
def save_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _set_saved(db, user, _get_job(db, user, job_id), "saved")
    return {"saved": True}


@router.delete("/jobs/{job_id}/save")
def unsave_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _set_saved(db, user, _get_job(db, user, job_id, include_inactive=True), None)
    return {"saved": False}


@router.post("/jobs/{job_id}/dismiss")
def dismiss_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _set_saved(db, user, _get_job(db, user, job_id, include_inactive=True), "dismissed")
    return {"dismissed": True}


@router.delete("/jobs/{job_id}/dismiss")
def undismiss_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _set_saved(db, user, _get_job(db, user, job_id, include_inactive=True), None)
    return {"dismissed": False}


@router.post("/jobs/{job_id}/analyze")
def analyze(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    posting = _get_job(db, user, job_id)
    match = load_match(db, user, posting)
    db.commit()
    return match


# ---------------------------------------------------------------------------
# Qualification questions (asked while preparing an application)
# ---------------------------------------------------------------------------


@router.get("/qualifications/open")
def open_qualifications(job_id: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(QualificationVerificationRequest).where(
        QualificationVerificationRequest.user_id == user.id,
        QualificationVerificationRequest.status == "open",
    )
    if job_id:
        stmt = stmt.where(QualificationVerificationRequest.job_posting_id == job_id)
    rows = db.scalars(stmt).all()
    jobs = {}
    for row in rows:
        if row.job_posting_id and row.job_posting_id not in jobs:
            posting = db.get(JobPosting, row.job_posting_id)
            jobs[row.job_posting_id] = {"title": posting.title, "company": posting.company} if posting else None
    return [
        {
            "id": row.id,
            "job_posting_id": row.job_posting_id,
            "job": jobs.get(row.job_posting_id),
            "normalized_name": row.normalized_name,
            "display_name": row.display_name,
            "prompt": row.prompt,
            "priority": row.priority,
            "min_years": row.min_years,
            "choices": ["yes", "learning", "no", "unsure", "skip"],
        }
        for row in rows
    ]


@router.post("/qualifications/answers")
def answer_qualifications(payload: AnswerBatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.applications import invalidate_user_approvals

    profile = get_profile(db, user)
    saved = []
    for answer in payload.answers:
        choice = answer.choice
        if choice not in {"yes", "learning", "no", "unsure", "skip"}:
            raise error(400, "invalid_choice", "Choice must be yes, learning, no, unsure, or skip.")
        status = {"yes": "confirmed", "learning": "in_progress", "no": "not_possessed", "unsure": "unsure", "skip": "skipped"}[choice]
        proficiency = "learning" if choice == "learning" else answer.proficiency
        context = answer.context
        if choice == "yes" and not context:
            context = _context_from_links(profile, answer.project_id, answer.experience_id)
        evidence = " ".join(part for part in [context, answer.accomplishment] if part)
        row = upsert_profile_skill(
            db,
            profile,
            answer.normalized_name,
            confirmation_status=status,
            source="user_reported",
            proficiency=proficiency,
            context=context,
            setting=answer.setting,
            duration_months=answer.duration_months,
            evidence=evidence or None,
            evidence_type="user_statement" if not answer.setting else answer.setting,
        )
        if answer.request_id:
            request = db.get(QualificationVerificationRequest, answer.request_id)
            if request and request.user_id == user.id:
                request.status = "answered" if choice != "skip" else "skipped"
        open_rows = db.scalars(
            select(QualificationVerificationRequest).where(
                QualificationVerificationRequest.user_id == user.id,
                QualificationVerificationRequest.normalized_name == row.skill.normalized_name,
                QualificationVerificationRequest.status == "open",
            )
        ).all()
        for request in open_rows:
            request.status = "answered" if choice != "skip" else "skipped"
        saved.append({"id": row.id, "normalized_name": row.skill.normalized_name, "confirmation_status": row.confirmation_status, "proficiency": row.proficiency, "source": row.source})
    snapshot_profile(db, profile)
    invalidate_user_approvals(db, user, "A confirmed skill changed the profile after approval.")
    match = None
    application = None
    if payload.job_id:
        from app.services.applications import refresh_after_answers

        posting = _get_job(db, user, payload.job_id, include_inactive=True)
        match = load_match(db, user, posting)
        refreshed = refresh_after_answers(db, user, posting)
        if refreshed is not None:
            application = {"id": refreshed.id, "status": refreshed.status}
    refresh_matches(db, user, profile)
    db.commit()
    return {"skills": saved, "match": match, "application": application}


def _context_from_links(profile, project_id: str | None, experience_id: str | None) -> str | None:
    if project_id:
        project = next((item for item in profile.projects if item.id == project_id), None)
        if project:
            return f"Used in the project {project.name}."
    if experience_id:
        role = next((item for item in profile.experiences if item.id == experience_id), None)
        if role:
            return f"Used as {role.title} at {role.employer}."
    return None


def _get_job(db: Session, user: User, job_id: str, include_inactive: bool = False) -> JobPosting:
    posting = db.get(JobPosting, job_id)
    if posting is None or not posting_visible(posting, user, get_settings()):
        raise not_found()
    if not posting.is_active and not include_inactive:
        raise not_found()
    return posting


__all__ = ["router", "EMPLOYERS"]
