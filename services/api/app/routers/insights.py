from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import (
    Application,
    CareerPlan,
    JobMatch,
    JobPosting,
    Notification,
    QualificationVerificationRequest,
    SavedJob,
    User,
)
from app.routers.common import error, not_found
from app.services.jsonutil import dumps, loads
from app.services.profile_ops import get_profile, snapshot_profile, upsert_profile_skill

router = APIRouter(prefix="/api/v1", tags=["insights"])


class SettingsIn(BaseModel):
    email_notifications: bool | None = None
    job_board_tokens: list[str] | None = None
    excluded_employers: list[str] | None = None
    min_qualification_score: int | None = None
    min_interest_score: int | None = None


class PlanIn(BaseModel):
    normalized_name: str
    display_name: str
    status: str


class CompletePlanIn(BaseModel):
    context: str
    setting: str | None = None
    accomplishment: str | None = None
    proficiency: str | None = None
    duration_months: int | None = None


@router.get("/assistant/brief")
def assistant_brief(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    profile = get_profile(db, user)
    roles = loads(profile.preferences.target_roles, []) if profile.preferences else []
    questions = db.scalars(
        select(QualificationVerificationRequest).where(
            QualificationVerificationRequest.user_id == user.id,
            QualificationVerificationRequest.status == "open",
        )
    ).all()
    applications = db.scalars(
        select(Application).where(
            Application.user_id == user.id,
            Application.status.in_(["awaiting_skill_verification", "awaiting_review", "approved"]),
        )
    ).all()
    matches = db.scalars(select(JobMatch).where(JobMatch.user_id == user.id)).all()
    ranked = sorted(matches, key=lambda item: ((item.career_interest_score or 0) + (item.qualification_score or 0)), reverse=True)
    suggestions = []
    for match in ranked:
        posting = db.get(JobPosting, match.job_posting_id)
        if posting is None or not posting.is_active or posting.is_sample:
            continue
        suggestions.append(
            {
                "id": posting.id,
                "title": posting.title,
                "company": posting.company,
                "source": posting.source,
                "is_sample": False,
                "qualification_score": match.qualification_score,
                "career_interest_score": match.career_interest_score,
            }
        )
        if len(suggestions) == 5:
            break
    return {
        "ai_configured": settings.ai_configured,
        "ai_note": (
            "Resume wording can be rewritten by the configured model, then kept only when it stays inside confirmed facts."
            if settings.ai_configured
            else "No AI key is configured. ApplyPilot still reorders your confirmed resume for each job and does not invent qualifications. Set AI_PROVIDER and a key for rewritten wording."
        ),
        "public_sources": ["remotive", "themuse", "arbeitnow"] if settings.public_job_sources else [],
        "target_roles": roles,
        "open_questions": [
            {"id": row.id, "job_posting_id": row.job_posting_id, "display_name": row.display_name, "prompt": row.prompt}
            for row in questions
        ],
        "queue": [
            {
                "id": item.id,
                "status": item.status,
                "job_posting_id": item.job_posting_id,
                "title": db.get(JobPosting, item.job_posting_id).title if db.get(JobPosting, item.job_posting_id) else None,
                "company": db.get(JobPosting, item.job_posting_id).company if db.get(JobPosting, item.job_posting_id) else None,
            }
            for item in applications
        ],
        "suggestions": suggestions,
        "does_not": "The assistant does not submit applications. You approve each draft.",
    }


@router.get("/analytics/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    applications = db.scalars(select(Application).where(Application.user_id == user.id)).all()
    jobs = db.scalars(select(JobPosting).where(JobPosting.is_active.is_(True))).all()
    visible = [job for job in jobs if job.user_id in {None, user.id} and (get_settings().demo_mode or not job.is_sample)]
    counts = Counter(item.status for item in applications)
    submitted = [item for item in applications if item.status in {"submitted", "interview", "offer", "rejected"}]
    live = [item for item in submitted if item.is_live_submission]
    simulated = [item for item in applications if item.submission_method == "simulated" and item.status == "submitted"]
    manual = [item for item in applications if item.submission_method == "manual" and item.status in {"submitted", "interview", "offer", "rejected"}]
    interviews = counts["interview"] + counts["offer"]
    offers = counts["offer"]
    submitted_count = len(submitted)
    conversion = round(100 * interviews / submitted_count, 1) if submitted_count else None
    return {
        "jobs_discovered": len(visible),
        "jobs_saved": db.scalar(select(func.count()).select_from(SavedJob).where(SavedJob.user_id == user.id)) or 0,
        "applications_prepared": len(applications),
        "applications_approved": counts["approved"] + len(submitted),
        "confirmed_live_submissions": len(live),
        "simulated_submissions": len(simulated),
        "user_confirmed_submissions": len(manual),
        "failed_submissions": counts["failed"],
        "pending_reviews": counts["awaiting_review"] + counts["awaiting_skill_verification"],
        "interviews": interviews,
        "offers": offers,
        "rejections": counts["rejected"],
        "interview_conversion_rate": conversion,
        "disclaimer": "Interview rate is a count of statuses you recorded. It is not evidence that a resume version caused interviews.",
        "by_status": dict(counts),
    }


@router.get("/career/gaps")
def gaps(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = get_profile(db, user)
    possessed = {
        row.skill.normalized_name
        for row in profile.profile_skills
        if row.confirmation_status == "confirmed"
    }
    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}
    postings = db.scalars(select(JobPosting).where(JobPosting.is_active.is_(True))).all()
    for posting in postings:
        if posting.user_id not in {None, user.id}:
            continue
        if posting.is_sample and not get_settings().demo_mode:
            continue
        seen = set()
        for requirement in posting.requirements:
            if requirement.category != "skill" or requirement.priority not in {"mandatory", "preferred"}:
                continue
            if requirement.normalized_name in seen:
                continue
            seen.add(requirement.normalized_name)
            counts[requirement.normalized_name] += 1
            labels[requirement.normalized_name] = requirement.name
    plans = {
        plan.normalized_name: plan.status
        for plan in db.scalars(select(CareerPlan).where(CareerPlan.user_id == user.id)).all()
    }
    recommendations = []
    for name, frequency in counts.most_common():
        if name in possessed:
            continue
        recommendations.append(
            {
                "normalized_name": name,
                "display_name": labels[name],
                "frequency": frequency,
                "plan_status": plans.get(name),
                "reason": f"Appears in {frequency} deduplicated posting(s) in the current catalog.",
            }
        )
    return {
        "disclaimer": "Recommendations reflect observed postings in your catalog, not guaranteed hiring outcomes.",
        "recommendations": recommendations,
    }


@router.post("/career/plans", status_code=201)
def set_plan(payload: PlanIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.status not in {"interested", "learning", "completed", "not_interested"}:
        raise error(400, "invalid_status", "Status must be interested, learning, completed, or not_interested.")
    if payload.status == "completed":
        raise error(400, "details_required", "Completing a skill requires the experience details endpoint. It is not added automatically.")
    plan = db.scalar(select(CareerPlan).where(CareerPlan.user_id == user.id, CareerPlan.normalized_name == payload.normalized_name))
    if plan is None:
        plan = CareerPlan(user_id=user.id, normalized_name=payload.normalized_name, display_name=payload.display_name)
        db.add(plan)
    plan.status = payload.status
    plan.display_name = payload.display_name
    db.commit()
    return {"id": plan.id, "status": plan.status}


@router.post("/career/plans/{plan_id}/complete")
def complete_plan(plan_id: str, payload: CompletePlanIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = db.get(CareerPlan, plan_id)
    if plan is None or plan.user_id != user.id:
        raise not_found()
    if not payload.context.strip():
        raise error(400, "details_required", "Describe where you used this skill before it is saved as a qualification.")
    profile = get_profile(db, user)
    upsert_profile_skill(
        db,
        profile,
        plan.display_name,
        confirmation_status="confirmed",
        source="user_reported",
        proficiency=payload.proficiency,
        context=payload.context,
        setting=payload.setting,
        duration_months=payload.duration_months,
        evidence=payload.accomplishment or payload.context,
    )
    plan.status = "completed"
    snapshot_profile(db, profile)
    db.commit()
    return {"id": plan.id, "status": plan.status}


@router.get("/notifications")
def notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc())).all()
    return [
        {"id": row.id, "title": row.title, "body": row.body, "read": row.read_at is not None, "created_at": row.created_at.isoformat()}
        for row in rows
    ]


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise not_found()
    row.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/settings")
def read_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = user.settings
    env = get_settings()
    return {
        "email_notifications": settings.email_notifications,
        "job_board_tokens": loads(settings.job_board_tokens, []),
        "excluded_employers": loads(settings.excluded_employers, []),
        "min_qualification_score": settings.min_qualification_score,
        "min_interest_score": settings.min_interest_score,
        "automation_policy": {
            "unattended_submission": False,
            "note": "Unattended submission is not enabled. Every application needs an explicit approval.",
        },
        "integrations": {
            "ai": env.ai_configured,
            "ai_provider": env.ai_provider if env.ai_configured else "none",
            "adzuna": env.adzuna_configured,
            "demo_mode": env.demo_mode,
            "live_submission": [],
        },
    }


@router.put("/settings")
def write_settings(payload: SettingsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = user.settings
    data = payload.model_dump(exclude_unset=True)
    if "email_notifications" in data:
        settings.email_notifications = bool(data["email_notifications"])
    if "job_board_tokens" in data:
        settings.job_board_tokens = dumps(data["job_board_tokens"])
    if "excluded_employers" in data:
        settings.excluded_employers = dumps(data["excluded_employers"])
    if "min_qualification_score" in data:
        settings.min_qualification_score = data["min_qualification_score"]
    if "min_interest_score" in data:
        settings.min_interest_score = data["min_interest_score"]
    db.commit()
    return {"ok": True}


@router.get("/home")
def home(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Everything the home screen needs in one request."""
    from datetime import timedelta

    from app.models import OriginalResume
    from app.services import search_profiles as profiles_service
    from app.services.job_search import JobFilters, search_jobs
    from app.services.job_sync import latest_discovery

    settings = get_settings()
    profile = get_profile(db, user)
    search = profiles_service.default_profile(db, user)
    filters = JobFilters.from_profile(search)
    filters.include_samples = False
    result = search_jobs(db, user, filters)
    items = result["items"]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    new_this_week = [item for item in items if (item.get("discovered_at") or "") >= week_ago]
    applications = db.scalars(select(Application).where(Application.user_id == user.id)).all()
    counts = Counter(item.status for item in applications)
    questions = db.scalars(
        select(QualificationVerificationRequest).where(QualificationVerificationRequest.user_id == user.id, QualificationVerificationRequest.status == "open")
    ).all()
    resumes = db.scalars(select(OriginalResume).where(OriginalResume.user_id == user.id)).all()
    approved_resume = any(row.approved_at for row in resumes)
    discovery = latest_discovery(db, user)
    db.commit()
    checklist = [
        {"key": "resume", "label": "Upload your resume", "done": bool(resumes), "href": "/onboarding"},
        {"key": "review", "label": "Review what ApplyPilot read", "done": approved_resume, "href": "/onboarding"},
        {"key": "links", "label": "Add your LinkedIn and GitHub links", "done": bool(profile.linkedin_url or profile.github_url), "href": "/profile"},
        {"key": "search", "label": "Set what jobs you want", "done": bool(search.updated_at and search.created_at and search.updated_at > search.created_at) or bool(discovery), "href": "/searches"},
        {"key": "discover", "label": "Find jobs", "done": bool(discovery), "href": "/jobs"},
        {"key": "ai", "label": "Connect Claude for AI rewriting (optional)", "done": settings.ai_configured, "href": "/settings"},
    ]
    return {
        "name": user.full_name,
        "checklist": checklist,
        "ai_configured": settings.ai_configured,
        "matches_total": len(items),
        "new_this_week": len(new_this_week),
        "top_matches": items[:6],
        "hidden": result["hidden"],
        "open_questions": len(questions),
        "pipeline": {
            "needs_answers": counts["awaiting_skill_verification"],
            "ready_for_review": counts["awaiting_review"] + counts["preparing"],
            "approved": counts["approved"],
            "finish_on_site": counts["manual_action_required"],
            "submitted": counts["submitted"],
            "interviews": counts["interview"],
            "offers": counts["offer"],
            "closed": counts["rejected"] + counts["withdrawn"],
        },
        "last_discovery": discovery,
        "search_profile": profiles_service.serialize(search),
    }


@router.get("/nav-counts")
def nav_counts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    questions = db.scalar(
        select(func.count()).select_from(QualificationVerificationRequest).where(QualificationVerificationRequest.user_id == user.id, QualificationVerificationRequest.status == "open")
    ) or 0
    review = db.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == user.id, Application.status.in_(["awaiting_review", "awaiting_skill_verification", "approved", "manual_action_required"]))
    ) or 0
    from app.models import ApplyRun

    waiting = db.scalar(select(func.count()).select_from(ApplyRun).where(ApplyRun.user_id == user.id, ApplyRun.status == "needs_you")) or 0
    return {"questions": questions, "applications": review, "apply_needs_you": waiting, "ai": get_settings().ai_configured}


@router.post("/ai/test")
def ai_test(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send one small request to the configured model and report the result. No secrets are returned."""
    import time

    from app.services.ai import AIError, ai_scope, get_provider

    settings = get_settings()
    provider = get_provider(settings, tier="fast")
    if provider is None:
        return {"ok": False, "configured": False, "message": "No AI key is configured. Add ANTHROPIC_API_KEY to services/api/.env (or run ./configure.sh ai)."}
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "reply": {"type": "string"}}, "required": ["ok", "reply"], "additionalProperties": False}
    started = time.monotonic()
    try:
        with ai_scope(user.id, "connection_test", db):
            result = provider.structured(system="You are a connection check.", user="Reply with ok=true and a three-word greeting.", schema=schema, max_tokens=200, effort="low")
    except AIError as exc:
        db.commit()
        return {"ok": False, "configured": True, "provider": provider.name, "model": getattr(provider, "model", None), "message": str(exc)}
    db.commit()
    return {
        "ok": bool(result.get("ok")),
        "configured": True,
        "provider": provider.name,
        "model": getattr(provider, "model", None),
        "reply": str(result.get("reply", ""))[:80],
        "latency_ms": round((time.monotonic() - started) * 1000),
    }


# ---------------------------------------------------------------------------
# AI usage and cost
# ---------------------------------------------------------------------------

FEATURE_LABELS = {
    "resume_tailoring": "Resume tailoring",
    "cover_letter": "Cover letters",
    "assistant": "Assistant",
    "resume_extraction": "Resume extraction check",
    "connection_test": "Connection test",
    "autofill": "Application autofill",
    "application_answers": "Application answers",
    "other": "Other",
}
QUALITY_MODELS = {"sonnet", "opus"}


class AISettingsIn(BaseModel):
    quality_model: str | None = None
    spend_limit_usd: float | None = None


def _ai_settings_out(user: User) -> dict:
    from app.services.ai import MODEL_LABELS

    env = get_settings()
    row = user.settings
    preference = (row.ai_quality_model or "sonnet") if row else "sonnet"
    limit = row.ai_spend_limit_usd if row and row.ai_spend_limit_usd is not None else env.ai_spend_limit_usd
    quality = env.anthropic_premium_model if preference == "opus" else env.anthropic_model
    return {
        "configured": env.ai_configured,
        "provider": env.ai_provider_name,
        "quality_model": preference,
        "models": {
            "quality": {"id": quality, "label": MODEL_LABELS.get(quality, quality), "used_for": "Resume rewriting, cover letters, assistant"},
            "fast": {"id": env.anthropic_fast_model, "label": MODEL_LABELS.get(env.anthropic_fast_model, env.anthropic_fast_model), "used_for": "Resume extraction checks, connection test"},
        },
        "spend_limit_usd": round(float(limit), 2),
        "default_spend_limit_usd": env.ai_spend_limit_usd,
    }


@router.get("/ai/usage")
def ai_usage(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Estimated spend from the token counts Anthropic reports on each response."""
    from datetime import timedelta

    from app.models import AICache, AIUsage
    from app.services.ai import MODEL_LABELS

    now = datetime.now(timezone.utc)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    week = now - timedelta(days=7)
    rows = db.scalars(select(AIUsage).where(AIUsage.user_id == user.id).order_by(AIUsage.created_at.desc())).all()

    def when(row):
        stamp = row.created_at
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)

    def total(items) -> dict:
        items = list(items)
        return {
            "cost_usd": round(sum(item.cost_usd for item in items), 6),
            "requests": len(items),
            "input_tokens": sum(item.input_tokens + item.cache_read_tokens + item.cache_write_tokens for item in items),
            "output_tokens": sum(item.output_tokens for item in items),
            "cached_tokens": sum(item.cache_read_tokens for item in items),
        }

    by_feature: dict[str, list] = {}
    by_model: dict[str, list] = {}
    for row in rows:
        by_feature.setdefault(row.feature, []).append(row)
        by_model.setdefault(row.model, []).append(row)
    settings_out = _ai_settings_out(user)
    spent = sum(row.cost_usd for row in rows)
    cache_hits = db.scalar(select(func.coalesce(func.sum(AICache.hits), 0)).where(AICache.user_id == user.id))
    return {
        **settings_out,
        "totals": {
            "all_time": total(rows),
            "this_month": total(row for row in rows if when(row) >= month),
            "last_7_days": total(row for row in rows if when(row) >= week),
            "today": total(row for row in rows if when(row) >= day),
        },
        "remaining_usd": round(max(settings_out["spend_limit_usd"] - spent, 0.0), 6),
        "limit_reached": spent >= settings_out["spend_limit_usd"],
        "cache_hits": int(cache_hits or 0),
        "by_feature": sorted(
            ({"feature": key, "label": FEATURE_LABELS.get(key, key.replace("_", " ").title()), **total(items)} for key, items in by_feature.items()),
            key=lambda item: -item["cost_usd"],
        ),
        "by_model": sorted(
            ({"model": key, "label": MODEL_LABELS.get(key, key), **total(items)} for key, items in by_model.items()),
            key=lambda item: -item["cost_usd"],
        ),
        "recent": [
            {
                "at": when(row).isoformat(),
                "feature": FEATURE_LABELS.get(row.feature, row.feature),
                "model": MODEL_LABELS.get(row.model, row.model),
                "input_tokens": row.input_tokens + row.cache_read_tokens + row.cache_write_tokens,
                "cached_tokens": row.cache_read_tokens,
                "output_tokens": row.output_tokens,
                "cost_usd": round(row.cost_usd, 6),
                "ok": row.ok,
            }
            for row in rows[:25]
        ],
        "note": "Estimates use Anthropic's published per-token prices and the token counts on each response. Your Anthropic console shows the billed amount.",
    }


@router.put("/ai/settings")
def write_ai_settings(payload: AISettingsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = user.settings
    data = payload.model_dump(exclude_unset=True)
    if "quality_model" in data:
        choice = (data["quality_model"] or "sonnet").lower()
        if choice not in QUALITY_MODELS:
            raise error(400, "invalid_model", "Choose sonnet or opus.")
        row.ai_quality_model = choice
    if "spend_limit_usd" in data:
        limit = data["spend_limit_usd"]
        if limit is None:
            row.ai_spend_limit_usd = None
        elif not 0 <= limit <= 1000:
            raise error(400, "invalid_limit", "Use a limit between $0 and $1,000.")
        else:
            row.ai_spend_limit_usd = round(float(limit), 2)
    db.commit()
    db.refresh(user)
    return _ai_settings_out(user)
