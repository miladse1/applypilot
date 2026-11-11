"""Filter and rank stored postings for one user and one search profile."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.security import ensure_utc
from app.models import JobMatch, JobPosting, SavedJob, SearchProfile, User
from app.services import taxonomy
from app.services.jsonutil import loads
from app.services.search_profiles import serialize


@dataclass
class JobFilters:
    families: list[str] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    posted_within_days: int | None = None
    employment_types: list[str] = field(default_factory=list)
    work_arrangements: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    exclude_companies: list[str] = field(default_factory=list)
    q: str = ""
    company: str = ""
    source: str = ""
    location: str = ""
    industry: str = ""
    seniority: str = ""
    employment_type: str = ""
    work_arrangement: str = ""
    min_salary: int | None = None
    min_qualification: int | None = None
    min_interest: int | None = None
    saved_only: bool = False
    include_samples: bool = True
    include_dismissed: bool = False
    sort: str = "relevance"
    # When the user names specific fields, generic "technology co-op" postings are left out.
    strict_families: bool = False

    @classmethod
    def from_profile(cls, profile: SearchProfile) -> "JobFilters":
        data = serialize(profile)
        return cls(
            families=data["role_families"],
            levels=data["levels"],
            scopes=data["location_scopes"],
            posted_within_days=data["posted_within_days"],
            employment_types=data["employment_types"],
            work_arrangements=data["work_arrangements"],
            exclude_keywords=data["exclude_keywords"],
            exclude_companies=data["exclude_companies"],
        )


def _visible(db: Session, user: User, *, include_inactive: bool = False):
    settings = get_settings()
    stmt = select(JobPosting).options(selectinload(JobPosting.requirements)).where(or_(JobPosting.user_id.is_(None), JobPosting.user_id == user.id))
    if not include_inactive:
        stmt = stmt.where(JobPosting.is_active.is_(True))
    if not settings.demo_mode:
        stmt = stmt.where(JobPosting.is_sample.is_(False))
    return db.scalars(stmt).all()


def _posted_or_found(posting: JobPosting) -> datetime | None:
    value = posting.posted_at or posting.discovered_at
    return ensure_utc(value) if value else None


def _skill_overlap(explanation: dict) -> tuple[float, list[str], list[str], list[str]]:
    items = [item for item in explanation.get("items", []) if item.get("category") == "skill" and item.get("priority") in {"mandatory", "preferred"}]
    matched = [item["name"] for item in items if item.get("status") == "matched"]
    partial = [item["name"] for item in items if item.get("status") == "partial"]
    unverified = [item["name"] for item in items if item.get("status") == "unverified"]
    missing = [item["name"] for item in items if item.get("status") == "not_possessed"]
    if not items:
        return 0.0, matched, unverified, missing
    # A related skill (AWS for an Azure requirement) counts half, but is never shown as "you have".
    return (len(matched) + 0.5 * len(partial)) / len(items), matched, unverified, missing


def search_jobs(db: Session, user: User, filters: JobFilters) -> dict:
    postings = _visible(db, user)
    saved_rows = db.scalars(select(SavedJob).where(SavedJob.user_id == user.id)).all()
    saved = {row.job_posting_id for row in saved_rows if (row.status or "saved") == "saved"}
    dismissed = {row.job_posting_id for row in saved_rows if row.status == "dismissed"}
    matches = {row.job_posting_id: row for row in db.scalars(select(JobMatch).where(JobMatch.user_id == user.id)).all()}
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=filters.posted_within_days) if filters.posted_within_days else None
    hidden: Counter[str] = Counter()
    items = []
    q = filters.q.lower().strip()
    for posting in postings:
        families = loads(posting.role_families, []) if posting.role_families else []
        level = posting.seniority or "unspecified"
        scope = posting.location_scope or "unknown"
        if posting.is_sample and not filters.include_samples:
            continue
        if posting.id in dismissed and not filters.include_dismissed:
            hidden["dismissed"] += 1
            continue
        if filters.saved_only and posting.id not in saved:
            continue
        blob = f"{posting.title} {posting.company} {posting.description}".lower()
        if q and q not in blob and not all(part in blob for part in q.split()):
            continue
        if filters.company and filters.company.lower() not in posting.company.lower():
            continue
        if filters.source and posting.source != filters.source:
            continue
        if filters.location and filters.location.lower() not in (posting.location or "").lower() and posting.work_arrangement != "remote":
            continue
        if filters.industry and filters.industry.lower() not in (posting.industry or "").lower():
            continue
        if filters.seniority and posting.seniority != filters.seniority:
            continue
        if filters.employment_type and posting.employment_type != filters.employment_type:
            continue
        if filters.work_arrangement and posting.work_arrangement != filters.work_arrangement:
            continue
        if filters.min_salary and (posting.salary_min or 0) < filters.min_salary:
            continue
        if filters.exclude_companies and any(name.lower() in posting.company.lower() for name in filters.exclude_companies if name):
            hidden["excluded"] += 1
            continue
        if filters.exclude_keywords and any(word.lower() in blob for word in filters.exclude_keywords if word):
            hidden["excluded"] += 1
            continue
        if not posting.is_sample:
            if filters.families:
                allowed = set(filters.families)
                general_ok = not filters.strict_families and "technology_general" in families and level in {"intern", "new_grad"}
                if not (set(families) & allowed) and not general_ok:
                    hidden["role"] += 1
                    continue
            if filters.levels and level not in filters.levels:
                hidden[f"level:{level}"] += 1
                continue
            if filters.scopes and scope not in filters.scopes:
                hidden[f"scope:{scope}"] += 1
                continue
            if cutoff and (_posted_or_found(posting) or now) < cutoff:
                hidden["older"] += 1
                continue
            if filters.employment_types and posting.employment_type not in filters.employment_types and posting.employment_type not in {"unknown", None}:
                hidden["type"] += 1
                continue
            if filters.work_arrangements and posting.work_arrangement not in filters.work_arrangements and posting.work_arrangement not in {"unknown", None}:
                hidden["arrangement"] += 1
                continue
        match = matches.get(posting.id)
        explanation = loads(match.explanation, {}) if match else {}
        qualification = match.qualification_score if match else None
        interest = match.career_interest_score if match else None
        if filters.min_qualification is not None and (qualification or 0) < filters.min_qualification:
            continue
        if filters.min_interest is not None and (interest or 0) < filters.min_interest:
            continue
        overlap, matched_skills, unverified, missing = _skill_overlap(explanation)
        relevance, reasons = taxonomy.relevance_score(
            families=families,
            wanted_families=filters.families,
            level=level,
            wanted_levels=filters.levels,
            scope=scope,
            posted_at=_posted_or_found(posting),
            skill_overlap=overlap,
        )
        card = job_card(posting, qualification, interest, explanation, posting.id in saved)
        card.update(
            relevance=relevance,
            relevance_reasons=reasons,
            matched_skills=matched_skills,
            unverified_skills=unverified,
            missing_skills=missing,
            skill_overlap=round(overlap, 2),
        )
        items.append(card)
    if filters.sort == "newest":
        items.sort(key=lambda item: item.get("posted_at") or item.get("discovered_at") or "", reverse=True)
    elif filters.sort == "match":
        items.sort(key=lambda item: (item.get("skill_overlap") or 0, item["relevance"]), reverse=True)
    else:
        items.sort(key=lambda item: (item["relevance"], item.get("posted_at") or ""), reverse=True)
    facets = {
        "levels": dict(Counter(item["level"] for item in items)),
        "scopes": dict(Counter(item["location_scope"] for item in items)),
        "families": dict(Counter(item["role_family"] or "other" for item in items)),
        "sources": dict(Counter(item["source"] for item in items)),
    }
    return {"items": items, "facets": facets, "hidden": _hidden_summary(hidden)}


def _hidden_summary(hidden: Counter) -> dict:
    levels = {key.split(":", 1)[1]: value for key, value in hidden.items() if key.startswith("level:")}
    scopes = {key.split(":", 1)[1]: value for key, value in hidden.items() if key.startswith("scope:")}
    return {
        "total": sum(hidden.values()),
        "by_level": levels,
        "by_scope": scopes,
        "other_roles": hidden.get("role", 0),
        "older": hidden.get("older", 0),
        "excluded": hidden.get("excluded", 0),
        "dismissed": hidden.get("dismissed", 0),
    }


def job_card(posting: JobPosting, qualification, interest, explanation: dict, saved: bool) -> dict:
    unverified = [item["name"] for item in explanation.get("unverified", [])] if explanation else []
    families = loads(posting.role_families, []) if posting.role_families else []
    level = posting.seniority or "unspecified"
    scope = posting.location_scope or "unknown"
    posted = posting.posted_at
    age = taxonomy.age_days(ensure_utc(posted)) if posted else None
    return {
        "id": posting.id,
        "title": posting.title,
        "company": posting.company,
        "industry": posting.industry,
        "location": posting.location,
        "work_arrangement": posting.work_arrangement,
        "employment_type": posting.employment_type,
        "seniority": posting.seniority,
        "level": level,
        "level_label": taxonomy.LEVELS.get(level, level),
        "level_reason": posting.level_reason,
        "experience_years": posting.experience_years,
        "role_family": posting.role_family,
        "role_families": families,
        "role_label": taxonomy.ROLE_FAMILIES.get(posting.role_family or "", {}).get("label"),
        "location_scope": scope,
        "location_label": taxonomy.LOCATION_SCOPES.get(scope, scope),
        "salary_min": posting.salary_min,
        "salary_max": posting.salary_max,
        "salary_currency": posting.salary_currency,
        "source": posting.source,
        "source_label": posting.source_label or posting.source,
        "also_seen_on": loads(posting.also_seen_on, []) if posting.also_seen_on else [],
        "is_sample": posting.is_sample,
        "is_user_added": posting.user_id is not None,
        "application_url": posting.application_url,
        "posted_at": ensure_utc(posted).isoformat() if posted else None,
        "posted_days_ago": age,
        "expires_at": ensure_utc(posting.expires_at).isoformat() if posting.expires_at else None,
        "discovered_at": ensure_utc(posting.discovered_at).isoformat() if posting.discovered_at else None,
        "last_verified_at": ensure_utc(posting.last_verified_at).isoformat() if posting.last_verified_at else None,
        "is_active": posting.is_active,
        "needs_detail": bool(posting.needs_detail),
        "qualification_score": qualification,
        "career_interest_score": interest,
        "unverified_skills": unverified,
        "required_skills": [item.name for item in posting.requirements if item.category == "skill" and item.priority == "mandatory"],
        "preferred_skills": [item.name for item in posting.requirements if item.category == "skill" and item.priority == "preferred"],
        "saved": saved,
        "score_disclaimer": "Scores are explainable assessments, not ATS scores or hiring probabilities.",
    }


# ---------------------------------------------------------------------------
# Saved searches on platforms that do not allow automated access
# ---------------------------------------------------------------------------


def external_searches(profile: SearchProfile) -> list[dict]:
    data = serialize(profile)
    families = data["role_families"] or taxonomy.DEFAULT_FAMILIES
    levels = data["levels"] or taxonomy.DEFAULT_LEVELS
    city = data["city"] or "Toronto"
    student = "intern" in levels or "new_grad" in levels
    primary = taxonomy.ROLE_FAMILIES.get(families[0], {}).get("search_terms", ["software developer"])[0] if families else "software developer"
    keyword = data["custom_titles"][0] if data["custom_titles"] else (f"{primary} intern" if "intern" in levels else primary)
    kw = quote_plus(keyword)
    loc = quote_plus(f"{city}, Ontario, Canada")
    linkedin_levels = []
    if "intern" in levels:
        linkedin_levels.append("1")
    if "entry" in levels or "new_grad" in levels:
        linkedin_levels.append("2")
    links = [
        {
            "platform": "LinkedIn Jobs",
            "kind": "job_board",
            "url": f"https://www.linkedin.com/jobs/search/?keywords={kw}&location={loc}&f_TPR=r604800&sortBy=DD" + (f"&f_E={'%2C'.join(linkedin_levels)}" if linkedin_levels else ""),
            "note": "Past week, internship and entry level. LinkedIn does not allow automated reading, so import postings you like with the ApplyPilot button or by pasting.",
        },
        {
            "platform": "Indeed Canada",
            "kind": "job_board",
            "url": f"https://ca.indeed.com/jobs?q={kw}&l={quote_plus(city + ', ON')}&fromage=7&sort=date",
            "note": "Sorted by date, last 7 days. Import postings with the ApplyPilot button or by pasting.",
        },
        {
            "platform": "Glassdoor",
            "kind": "job_board",
            "url": f"https://www.glassdoor.ca/Job/jobs.htm?sc.keyword={kw}&locKeyword={quote_plus(city)}&fromAge=7",
            "note": "Import postings by pasting the description.",
        },
        {
            "platform": "TalentEgg",
            "kind": "student",
            "url": f"https://talentegg.ca/jobs?keyword={kw}",
            "note": "Canadian student and new-grad board.",
        },
        {
            "platform": "Magnet",
            "kind": "student",
            "url": "https://magnet.today/",
            "note": "Ontario student and early-career matching platform.",
        },
        {
            "platform": "Experience York (co-op, work-study, research)",
            "kind": "university",
            "url": "https://experience.yorku.ca/",
            "note": "Sign in with Passport York. Lassonde co-op and work-study postings are behind sign-in, so ApplyPilot cannot read them. Use the import button on a posting you open.",
        },
        {
            "platform": "Lassonde Co-op & Internship Program",
            "kind": "university",
            "url": "https://lassonde.yorku.ca/student-life/co-op-and-internship-program",
            "note": "Program information and deadlines.",
        },
        {
            "platform": "Federal Student Work Experience Program",
            "kind": "government",
            "url": "https://www.canada.ca/en/public-service-commission/jobs/services/recruitment/students/federal-student-work-program.html",
            "note": "Government of Canada student jobs.",
        },
        {
            "platform": "Ontario Public Service careers",
            "kind": "government",
            "url": f"https://www.gojobs.gov.on.ca/Search.aspx?q={kw}",
            "note": "Includes student and internship programs.",
        },
        {
            "platform": "Job Bank",
            "kind": "job_board",
            "url": f"https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring={kw}&locationstring={quote_plus(city + ', ON')}&sort=D",
            "note": "Also searched automatically. This opens the same search on Job Bank.",
        },
        {
            "platform": "Google Careers",
            "kind": "employer",
            "url": f"https://www.google.com/about/careers/applications/jobs/results?location={quote_plus('Toronto, ON, Canada')}&q={quote_plus(primary)}" + ("&target_level=INTERN_AND_APPRENTICE&target_level=EARLY" if student else ""),
            "note": "Google has no public listing feed. Import postings from this page.",
        },
        {
            "platform": "Microsoft Careers",
            "kind": "employer",
            "url": f"https://jobs.careers.microsoft.com/global/en/search?q={quote_plus(primary)}&lc=Canada" + ("&exp=Students%20and%20graduates" if student else ""),
            "note": "Microsoft has no public listing feed. Import postings from this page.",
        },
        {
            "platform": "Shopify Careers",
            "kind": "employer",
            "url": f"https://www.shopify.com/careers/search?keywords={quote_plus(primary)}",
            "note": "Shopify is remote-first in Canada. Import postings from this page.",
        },
        {
            "platform": "OpenText Careers",
            "kind": "employer",
            "url": f"https://careers.opentext.com/us/en/search-results?keywords={quote_plus(primary)}",
            "note": "Import postings from this page.",
        },
        {
            "platform": "Intact Careers",
            "kind": "employer",
            "url": f"https://careers.intact.ca/ca/en/search-results?keywords={quote_plus(primary)}",
            "note": "Import postings from this page.",
        },
        {
            "platform": "CGI Careers",
            "kind": "employer",
            "url": "https://www.cgi.com/en/careers",
            "note": "Import postings from this page.",
        },
    ]
    return links
