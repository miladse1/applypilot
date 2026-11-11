from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Application, ApplicationStatusEvent, CoverLetter, JobPosting, SubmissionAttempt, User
from app.routers.common import error, not_found
from app.services.applications import (
    TransitionError,
    approve_application,
    confirm_manual,
    prepare_application,
    replace_answers,
    submit_application,
    update_status,
    valid_approval,
)
from app.models import QualificationVerificationRequest, ResumeVersion
from app.services.job_sync import posting_visible
from app.services.jsonutil import loads
from app.services.profile_ops import get_profile
from app.services.writing import write_cover_letter

router = APIRouter(prefix="/api/v1", tags=["applications"])


class DraftIn(BaseModel):
    job_id: str
    template: str = "original"
    length: str = "standard"
    tone: str = "professional"
    include_cover_letter: bool = False  # written later, only if an employer form asks for one
    use_ai: bool = True


class BatchDraftIn(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=25)
    tone: str = "professional"
    include_cover_letter: bool = False  # written later, only if an employer form asks for one


class LetterIn(BaseModel):
    tone: str = "professional"


class DraftPatch(BaseModel):
    answers: list[dict] | None = None
    notes: str | None = None
    cover_letter: str | None = None


class ApproveIn(BaseModel):
    acknowledge_unverified: bool = False
    acknowledge_gaps: bool = False


class BatchApproveIn(BaseModel):
    application_ids: list[str] = Field(min_length=1)
    acknowledge_unverified: bool = False
    acknowledge_gaps: bool = False


class SubmitIn(BaseModel):
    method: str
    simulate_failure: bool = False
    defer_sensitive: bool = False


class ManualConfirmIn(BaseModel):
    note: str = Field(min_length=3)


class StatusIn(BaseModel):
    status: str
    note: str = ""
    interview_at: datetime | None = None


@router.post("/applications", status_code=201)
def create_application(payload: DraftIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    posting = db.get(JobPosting, payload.job_id)
    if posting is None or not posting_visible(posting, user, get_settings()):
        raise not_found()
    try:
        application = prepare_application(
            db,
            user,
            posting,
            template=payload.template,
            length=payload.length,
            tone=payload.tone,
            include_cover_letter=payload.include_cover_letter,
        )
    except TransitionError as exc:
        raise error(409, "invalid_transition", str(exc)) from exc
    db.commit()
    return _application_out(db, application)


@router.post("/applications/batch", status_code=201)
def create_batch(payload: BatchDraftIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Prepare drafts for several jobs. Nothing is submitted; each draft waits for review."""
    results = []
    for job_id in dict.fromkeys(payload.job_ids):
        posting = db.get(JobPosting, job_id)
        if posting is None or not posting_visible(posting, user, get_settings()):
            results.append({"job_id": job_id, "ok": False, "error": "Job not found."})
            continue
        try:
            application = prepare_application(db, user, posting, tone=payload.tone, include_cover_letter=payload.include_cover_letter)
            db.commit()
            results.append({"job_id": job_id, "ok": True, "application": _application_out(db, application)})
        except TransitionError as exc:
            db.rollback()
            results.append({"job_id": job_id, "ok": False, "error": str(exc)})
    questions = db.scalars(
        select(QualificationVerificationRequest).where(QualificationVerificationRequest.user_id == user.id, QualificationVerificationRequest.status == "open")
    ).all()
    return {"results": results, "open_questions": len(questions)}


@router.get("/applications")
def list_applications(status: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Application).where(Application.user_id == user.id)
    if status:
        stmt = stmt.where(Application.status == status)
    rows = db.scalars(stmt.order_by(Application.updated_at.desc())).all()
    return [_application_out(db, row) for row in rows]


@router.get("/applications/{application_id}")
def get_application(application_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    application = _owned(db, user, application_id)
    return _application_out(db, application, detail=True)


@router.patch("/applications/{application_id}")
def patch_application(application_id: str, payload: DraftPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    application = _owned(db, user, application_id)
    if payload.notes is not None:
        application.notes = payload.notes
    if payload.answers is not None:
        replace_answers(db, application, payload.answers)
    if payload.cover_letter is not None and application.cover_letter_id:
        letter = db.get(CoverLetter, application.cover_letter_id)
        if letter and letter.user_id == user.id:
            letter.body = payload.cover_letter
            from app.services.applications import touch_draft

            touch_draft(db, application, "The cover letter changed after approval.")
    db.commit()
    return _application_out(db, application, detail=True)


@router.post("/applications/{application_id}/approve")
def approve(application_id: str, payload: ApproveIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    application = _owned(db, user, application_id)
    try:
        approve_application(
            db,
            user,
            application,
            acknowledge_unverified=payload.acknowledge_unverified,
            acknowledge_gaps=payload.acknowledge_gaps,
        )
    except TransitionError as exc:
        raise error(409, "invalid_transition", str(exc)) from exc
    db.commit()
    return _application_out(db, application)


@router.post("/applications/approve-batch")
def approve_batch(payload: BatchApproveIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    approved = []
    for application_id in payload.application_ids:
        application = _owned(db, user, application_id)
        try:
            approve_application(
                db,
                user,
                application,
                acknowledge_unverified=payload.acknowledge_unverified,
                acknowledge_gaps=payload.acknowledge_gaps,
            )
        except TransitionError as exc:
            raise error(409, "invalid_transition", f"{application_id}: {exc}") from exc
        approved.append(application.id)
    db.commit()
    return {"approved_ids": approved}


@router.post("/applications/{application_id}/reject")
def reject_draft(application_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    application = _owned(db, user, application_id)
    try:
        update_status(db, application, "withdrawn", "User rejected this draft.", None)
    except TransitionError as exc:
        raise error(409, "invalid_transition", str(exc)) from exc
    db.commit()
    return _application_out(db, application)


@router.post("/applications/{application_id}/submit")
def submit(application_id: str, payload: SubmitIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.simulate_failure and not get_settings().demo_mode:
        raise error(403, "demo_only", "Failure simulation is available only in demo mode.")
    application = _owned(db, user, application_id)
    try:
        result = submit_application(
            db,
            user,
            application,
            method=payload.method,
            simulate_failure=payload.simulate_failure,
            defer_sensitive=payload.defer_sensitive,
        )
    except TransitionError as exc:
        db.rollback()
        raise error(409, "invalid_transition", str(exc)) from exc
    db.commit()
    return result


@router.post("/applications/{application_id}/confirm-manual")
def confirm(application_id: str, payload: ManualConfirmIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    application = _owned(db, user, application_id)
    try:
        result = confirm_manual(db, user, application, payload.note)
    except TransitionError as exc:
        raise error(409, "invalid_transition", str(exc)) from exc
    db.commit()
    return result


@router.post("/applications/{application_id}/status")
def set_status(application_id: str, payload: StatusIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    application = _owned(db, user, application_id)
    try:
        update_status(db, application, payload.status, payload.note, payload.interview_at)
    except TransitionError as exc:
        raise error(409, "invalid_transition", str(exc)) from exc
    db.commit()
    return _application_out(db, application)


@router.get("/applications/{application_id}/history")
def history(application_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    application = _owned(db, user, application_id)
    events = db.scalars(
        select(ApplicationStatusEvent)
        .where(ApplicationStatusEvent.application_id == application.id)
        .order_by(ApplicationStatusEvent.created_at)
    ).all()
    attempts = db.scalars(
        select(SubmissionAttempt).where(SubmissionAttempt.application_id == application.id)
    ).all()
    return {
        "events": [
            {"from": event.from_status, "to": event.to_status, "note": event.note, "at": event.created_at.isoformat()}
            for event in events
        ],
        "attempts": [
            {
                "method": attempt.method,
                "status": attempt.status,
                "is_live": attempt.is_live,
                "confirmation_id": attempt.confirmation_id,
                "error": attempt.error,
            }
            for attempt in attempts
        ],
    }


@router.post("/cover-letters", status_code=201)
def create_letter(payload: DraftIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    posting = db.get(JobPosting, payload.job_id)
    if posting is None or not posting_visible(posting, user, get_settings()):
        raise not_found()
    profile = get_profile(db, user)
    body, info = write_cover_letter(profile, posting, _document_for(db, user, posting), payload.tone)
    letter = CoverLetter(user_id=user.id, job_posting_id=posting.id, tone=payload.tone, body=body)
    db.add(letter)
    db.commit()
    return {"id": letter.id, "body": letter.body, "tone": letter.tone, "generation": info}


@router.post("/applications/{application_id}/cover-letter")
def regenerate_letter(application_id: str, payload: LetterIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.applications import touch_draft

    application = _owned(db, user, application_id)
    posting = db.get(JobPosting, application.job_posting_id)
    profile = get_profile(db, user)
    body, info = write_cover_letter(profile, posting, _document_for(db, user, posting, application), payload.tone, fresh=True)
    letter = CoverLetter(user_id=user.id, job_posting_id=posting.id, tone=payload.tone, body=body)
    db.add(letter)
    db.flush()
    application.cover_letter_id = letter.id
    touch_draft(db, application, "A new cover letter was written.")
    db.commit()
    return {**_application_out(db, application, detail=True), "letter_generation": info}


def _document_for(db: Session, user: User, posting: JobPosting, application: Application | None = None) -> dict:
    version_id = application.resume_version_id if application else None
    version = db.get(ResumeVersion, version_id) if version_id else None
    if version is None:
        version = db.scalar(
            select(ResumeVersion).where(ResumeVersion.user_id == user.id, ResumeVersion.job_posting_id == posting.id).order_by(ResumeVersion.created_at.desc())
        )
    if version is not None:
        content = loads(version.content_json, {})
        if content.get("format") == "document":
            return content.get("document") or {}
    from app.services.resume_import import primary_resume
    from app.services.tailoring import source_document

    document, _style, _origin = source_document(get_profile(db, user), primary_resume(db, user))
    return document


def _owned(db: Session, user: User, application_id: str) -> Application:
    application = db.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise not_found()
    return application


STAGES = {
    "preparing": "Preparing",
    "awaiting_skill_verification": "Needs your answers",
    "awaiting_review": "Ready for review",
    "approved": "Approved",
    "submitting": "Submitting",
    "manual_action_required": "Finish on employer site",
    "submitted": "Submitted",
    "failed": "Submission failed",
    "interview": "Interviewing",
    "offer": "Offer",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
}


def submission_label(application: Application) -> str | None:
    if application.status not in {"submitted", "interview", "offer", "rejected"} and application.status != "withdrawn":
        return None
    if application.is_live_submission and application.submission_method == "browser":
        return "Submitted by ApplyPilot (employer confirmed)"
    if application.is_live_submission:
        return "Submitted (confirmed by the employer system)"
    if application.submission_method == "simulated":
        return "Simulated (not sent to the employer)"
    if application.submission_method == "manual":
        return "Submitted by you (you confirmed it)"
    if application.submission_method == "browser":
        return "Submitted by ApplyPilot (you confirmed it)"
    return None


def _application_out(db: Session, application: Application, detail: bool = False) -> dict:
    posting = db.get(JobPosting, application.job_posting_id)
    approval = valid_approval(db, application)
    version = db.get(ResumeVersion, application.resume_version_id) if application.resume_version_id else None
    version_content = loads(version.content_json, {}) if version else {}
    open_questions = db.scalars(
        select(QualificationVerificationRequest).where(
            QualificationVerificationRequest.user_id == application.user_id,
            QualificationVerificationRequest.job_posting_id == application.job_posting_id,
            QualificationVerificationRequest.status == "open",
        )
    ).all()
    payload = {
        "stage": STAGES.get(application.status, application.status),
        "submission_label": submission_label(application),
        "open_questions": len(open_questions),
        "source": posting.source if posting else None,
        "source_label": posting.source_label if posting else None,
        "is_sample": posting.is_sample if posting else False,
        "posting_active": posting.is_active if posting else False,
        "interview_at": application.interview_at.isoformat() if application.interview_at else None,
        "created_at": application.created_at.isoformat() if application.created_at else None,
        "updated_at": application.updated_at.isoformat() if application.updated_at else None,
        "resume": {
            "id": version.id,
            "title": version.title,
            "format": version_content.get("format", "legacy"),
            "generation": version_content.get("generation"),
            "keywords": version_content.get("keywords"),
            "change_count": len(version_content.get("changes") or []),
        } if version else None,
        "id": application.id,
        "job_posting_id": application.job_posting_id,
        "title": posting.title if posting else None,
        "company": posting.company if posting else None,
        "location": posting.location if posting else None,
        "application_url": posting.application_url if posting else None,
        "status": application.status,
        "draft_version": application.draft_version,
        "resume_version_id": application.resume_version_id,
        "cover_letter_id": application.cover_letter_id,
        "submission_method": application.submission_method,
        "is_live_submission": application.is_live_submission,
        "confirmation_id": application.confirmation_id,
        "notes": application.notes,
        "approval_valid": approval is not None,
        "autoapply": autoapply_support(posting),
        "submit_on": submission_channels(db, application, posting),
        "approved_draft_version": approval.draft_version if approval else None,
    }
    if detail:
        letter = db.get(CoverLetter, application.cover_letter_id) if application.cover_letter_id else None
        payload["answers"] = loads(application.answers_json, [])
        payload["cover_letter"] = letter.body if letter else None
        payload["cover_letter_tone"] = letter.tone if letter else None
        payload["questions"] = [
            {"id": row.id, "normalized_name": row.normalized_name, "display_name": row.display_name, "prompt": row.prompt, "priority": row.priority, "min_years": row.min_years}
            for row in open_questions
        ]
        payload["job"] = {
            "description": posting.description if posting else "",
            "employment_type": posting.employment_type if posting else None,
            "work_arrangement": posting.work_arrangement if posting else None,
            "posted_at": posting.posted_at.isoformat() if posting and posting.posted_at else None,
        }
        payload["apply_guide"] = apply_guide(posting)
    return payload


DONE_STATUSES = {"submitted", "interview", "offer", "rejected"}


def submission_channels(db: Session, application: Application, posting: JobPosting | None) -> list[dict]:
    """Where this application must be sent, when that is more than the employer's site, and what is done."""
    from app.models import PortalPosting
    from app.services.capture import channels

    if posting is None:
        return []
    rows = db.scalars(select(PortalPosting).where(PortalPosting.user_id == application.user_id, PortalPosting.job_posting_id == posting.id)).all()
    out: dict[str, dict] = {}
    for row in rows:
        for channel in channels(row, posting):
            if channel == "york":
                out["york"] = {"key": "york", "name": "Experience York", "url": row.url, "deadline": row.deadline, "documents": row.documents,
                               "how": "Submit on Experience York with your tailored resume PDF (and any documents the posting lists), then mark it done here.",
                               "done": application.portal_submitted_at is not None, "done_at": application.portal_submitted_at.isoformat() if application.portal_submitted_at else None}
            elif channel == "linkedin":
                out["linkedin"] = {"key": "linkedin", "name": "LinkedIn Easy Apply", "url": row.url, "deadline": None, "documents": None,
                                   "how": "LinkedIn does not allow automated applications. Apply with Easy Apply yourself, using the tailored resume PDF, then mark it done here.",
                                   "done": application.portal_submitted_at is not None, "done_at": application.portal_submitted_at.isoformat() if application.portal_submitted_at else None}
            elif channel == "employer":
                out["employer"] = {"key": "employer", "name": "Employer's website", "url": row.employer_url or posting.application_url, "deadline": row.deadline, "documents": None,
                                   "how": "ApplyPilot can fill and submit this one." if row.employer_url or "linkedin.com" not in (posting.application_url or "") else "Open the posting on LinkedIn in the ApplyPilot window and click Apply once, so ApplyPilot learns the employer's link.",
                                   "done": application.status in DONE_STATUSES, "done_at": None}
    return list(out.values()) if len(out) > 1 or "employer" not in out else []


class PortalDoneIn(BaseModel):
    done: bool = True


@router.post("/applications/{application_id}/portal-submitted")
def portal_submitted(application_id: str, payload: PortalDoneIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """You submitted this application on Experience York (or LinkedIn Easy Apply)."""
    from datetime import timezone

    application = db.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise not_found()
    application.portal_submitted_at = datetime.now(timezone.utc) if payload.done else None
    db.commit()
    return _application_out(db, application, detail=True)


def autoapply_support(posting: JobPosting | None) -> dict:
    from app.services.autoapply.records import support_for

    return support_for(posting)


def apply_guide(posting: JobPosting | None) -> dict:
    """What finishing the application on the employer's site will involve."""
    if posting is None:
        return {}
    platform = posting.source if posting.source in {"greenhouse", "lever", "ashby", "workday", "successfactors", "amazon", "ibm", "jibe", "jobbank"} else None
    url = posting.application_url or ""
    if not platform:
        lowered = url.lower()
        for name in ("greenhouse", "lever", "ashby", "myworkdayjobs", "icims", "taleo", "successfactors", "linkedin", "indeed"):
            if name in lowered:
                platform = "workday" if name == "myworkdayjobs" else name
                break
    steps = {
        "workday": ["Workday asks you to sign in or create an account for this employer.", "Choose “Autofill with Resume” and upload the PDF below, then correct any fields it misreads.", "Paste answers from below where the questions match."],
        "greenhouse": ["Greenhouse forms do not need an account.", "Upload the PDF below and paste the cover letter text.", "Fill the short questions from your saved answers."],
        "lever": ["Lever forms do not need an account.", "Upload the PDF below. Lever reads your name, email, and links from it.", "Paste the cover letter into “Additional information” if there is no upload field."],
        "ashby": ["Ashby forms do not need an account.", "Upload the PDF below and paste answers where asked."],
        "successfactors": ["SuccessFactors asks you to create a candidate profile.", "Upload the PDF below; review the parsed fields carefully."],
        "linkedin": ["Use LinkedIn Easy Apply or the employer link on the posting.", "Upload the tailored PDF instead of your default resume."],
        "indeed": ["Apply on Indeed or follow the link to the employer site.", "Upload the tailored PDF instead of your Indeed resume."],
        "jobbank": ["Job Bank lists how to apply (email, website, or in person) on the posting.", "If it says email, send the PDF and cover letter from your own email."],
    }
    return {
        "platform": platform,
        "url": url,
        "steps": steps.get(platform or "", ["Open the original posting and follow the employer's instructions.", "Upload the tailored PDF and paste the cover letter and answers below."]),
        "submission_note": "ApplyPilot does not submit on your behalf to this site. Submit it yourself, then mark it as submitted here.",
    }
