"""Application drafts, approval locking, and submission records.

A simulated success is stored as simulated. It is never a live employer submission.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationApproval,
    ApplicationStatusEvent,
    CoverLetter,
    JobPosting,
    Notification,
    SubmissionAttempt,
    User,
)
from app.services.writing import draft_answers as writing_answers
from app.services.writing import saved_answer_values, write_cover_letter
from app.services.jsonutil import dumps, loads
from app.services.matching import build_assessment
from app.services.profile_ops import get_profile
# Imported for its side effect: loads app.services.documents (and its AI imports) at startup.
# Removing it changes import order and lets tests that patch app.services.ai leak into later tests.
from app.services.documents import TruthfulnessError  # noqa: F401

TRANSITIONS: dict[str, set[str]] = {
    "discovered": {"saved", "preparing", "withdrawn"},
    "saved": {"preparing", "withdrawn"},
    "preparing": {"awaiting_skill_verification", "awaiting_review", "withdrawn"},
    "awaiting_skill_verification": {"preparing", "awaiting_review", "withdrawn"},
    "awaiting_review": {"approved", "preparing", "withdrawn"},
    "approved": {"submitting", "awaiting_review", "withdrawn"},
    # Back to approved only when a browser run stopped before anything was sent.
    "submitting": {"submitted", "failed", "manual_action_required", "approved"},
    "manual_action_required": {"submitted", "failed", "withdrawn"},
    "failed": {"submitting", "awaiting_review", "withdrawn"},
    "submitted": {"interview", "offer", "rejected", "withdrawn"},
    "interview": {"offer", "rejected", "withdrawn"},
    "offer": {"withdrawn"},
    "rejected": set(),
    "withdrawn": set(),
}

TERMINAL_INACTIVE = {"rejected", "withdrawn"}
SENSITIVE_KEYS = {
    "work_authorization",
    "sponsorship",
    "start_date",
    "relocation",
    "clearance",
    "license",
    "criminal_history",
    "disability",
    "demographics",
}


class TransitionError(Exception):
    pass


def transition(db: Session, application: Application, to_status: str, note: str = "") -> None:
    allowed = TRANSITIONS.get(application.status, set())
    if to_status not in allowed:
        raise TransitionError(f"Cannot move an application from {application.status} to {to_status}.")
    event = ApplicationStatusEvent(
        application_id=application.id,
        user_id=application.user_id,
        from_status=application.status,
        to_status=to_status,
        note=note,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    application.status = to_status
    if to_status in TERMINAL_INACTIVE:
        application.active_slot = None
    else:
        application.active_slot = application.job_posting_id


def prepare_application(
    db: Session,
    user: User,
    posting: JobPosting,
    *,
    template: str = "original",
    length: str = "standard",
    tone: str = "professional",
    include_cover_letter: bool = False,
    use_ai: bool = True,
) -> Application:
    existing = db.scalar(
        select(Application).where(Application.user_id == user.id, Application.active_slot == posting.id)
    )
    if existing:
        return existing
    from app.models import ProfileVersion
    from app.services.job_enrich import enrich_posting
    from app.services.job_sync import queue_verification_for_job
    from app.services.resume_import import create_tailored_version

    if posting.needs_detail or len(posting.description or "") < 400:
        # Read the full posting before analyzing it. Network problems leave the stored text in place.
        try:
            enrich_posting(db, posting)
        except Exception:  # noqa: BLE001
            pass
    profile = get_profile(db, user)
    queue_verification_for_job(db, user, profile, posting)
    assessment = build_assessment(profile, posting)
    latest_row = db.scalar(
        select(ProfileVersion)
        .where(ProfileVersion.profile_id == profile.id)
        .order_by(ProfileVersion.version_number.desc())
    )
    latest = latest_row.id if latest_row else None
    resume = _reusable_version(db, user, posting) or create_tailored_version(db, user, posting, use_ai=use_ai, profile_version_id=latest)
    content = loads(resume.content_json, {})
    document = content.get("document") or {}
    letter = None
    if include_cover_letter:
        body, info = write_cover_letter(profile, posting, document, tone)
        letter = CoverLetter(user_id=user.id, job_posting_id=posting.id, profile_version_id=latest, tone=tone, body=body)
        db.add(letter)
        db.flush()
    status = "awaiting_skill_verification" if _open_questions(db, user, posting) else "awaiting_review"
    application = Application(
        user_id=user.id,
        job_posting_id=posting.id,
        active_slot=posting.id,
        status="preparing",
        profile_version_id=latest,
        resume_version_id=resume.id,
        cover_letter_id=letter.id if letter else None,
        answers_json=dumps(_with_saved_answers(db, user, writing_answers(profile, posting, document))),
    )
    db.add(application)
    db.flush()
    note = "Draft prepared from your resume and profile."
    if assessment["unknown_count"]:
        note += f" {assessment['unknown_count']} requirement(s) need your answer."
    transition(db, application, status, note)
    return application


def _reusable_version(db: Session, user: User, posting: JobPosting):
    """The newest tailored version of the main resume for this job, including any edits the user made to it."""
    from app.models import ResumeVersion
    from app.services.resume_import import primary_resume

    primary = primary_resume(db, user)
    version = db.scalar(
        select(ResumeVersion)
        .where(ResumeVersion.user_id == user.id, ResumeVersion.job_posting_id == posting.id, ResumeVersion.kind == "tailored")
        .order_by(ResumeVersion.created_at.desc())
    )
    if version is None or primary is None or version.original_resume_id != primary.id:
        return None
    return version if loads(version.content_json, {}).get("format") == "document" else None


def _open_questions(db: Session, user: User, posting: JobPosting) -> int:
    from app.models import QualificationVerificationRequest

    return len(
        db.scalars(
            select(QualificationVerificationRequest).where(
                QualificationVerificationRequest.user_id == user.id,
                QualificationVerificationRequest.job_posting_id == posting.id,
                QualificationVerificationRequest.status == "open",
            )
        ).all()
    )


def refresh_after_answers(db: Session, user: User, posting: JobPosting) -> Application | None:
    """After skill questions are answered, rebuild the draft resume so confirmed skills are used."""
    from app.services.resume_import import create_tailored_version

    application = db.scalar(select(Application).where(Application.user_id == user.id, Application.active_slot == posting.id))
    if application is None or application.status not in {"preparing", "awaiting_skill_verification", "awaiting_review", "approved"}:
        return application
    resume = create_tailored_version(db, user, posting)
    application.resume_version_id = resume.id
    touch_draft(db, application, "The resume was rebuilt with your new answers.")
    if application.status == "awaiting_skill_verification" and not _open_questions(db, user, posting):
        transition(db, application, "awaiting_review", "All questions for this job are answered.")
    return application


def _with_saved_answers(db: Session, user: User, answers: list[dict]) -> list[dict]:
    saved = saved_answer_values(db, user)
    for item in answers:
        if item.get("sensitive") and not item.get("answer") and saved.get(item["key"]):
            item["answer"] = saved[item["key"]]
            item["from_saved"] = True
    return answers


def valid_approval(db: Session, application: Application) -> ApplicationApproval | None:
    approval = db.scalar(
        select(ApplicationApproval)
        .where(
            ApplicationApproval.application_id == application.id,
            ApplicationApproval.invalidated_at.is_(None),
        )
        .order_by(ApplicationApproval.approved_at.desc())
    )
    if approval is None:
        return None
    if approval.draft_version != application.draft_version:
        return None
    if approval.resume_version_id != application.resume_version_id:
        return None
    if approval.cover_letter_id != application.cover_letter_id:
        return None
    return approval


def invalidate_approval(db: Session, application: Application, reason: str) -> None:
    now = datetime.now(timezone.utc)
    approvals = db.scalars(
        select(ApplicationApproval).where(
            ApplicationApproval.application_id == application.id,
            ApplicationApproval.invalidated_at.is_(None),
        )
    ).all()
    for approval in approvals:
        approval.invalidated_at = now
    if application.status == "approved":
        transition(db, application, "awaiting_review", reason)


def invalidate_user_approvals(db: Session, user: User, reason: str) -> None:
    applications = db.scalars(
        select(Application).where(Application.user_id == user.id, Application.status == "approved")
    ).all()
    for application in applications:
        invalidate_approval(db, application, reason)
    submitted = db.scalars(
        select(Application).where(Application.user_id == user.id, Application.status == "submitted")
    ).all()
    for application in submitted:
        posting = db.get(JobPosting, application.job_posting_id)
        role = f"{posting.title} at {posting.company}" if posting else "a role"
        db.add(
            Notification(
                user_id=user.id,
                title="Profile updated after submission",
                body=(
                    f"Your profile changed after your application for {role} was recorded. "
                    "The submitted record was not altered. Regenerate documents before any new submission."
                ),
                created_at=datetime.now(timezone.utc),
            )
        )


def touch_draft(db: Session, application: Application, reason: str) -> None:
    application.draft_version += 1
    invalidate_approval(db, application, reason)


def approve_application(db: Session, user: User, application: Application, *, acknowledge_unverified: bool, acknowledge_gaps: bool) -> Application:
    if application.resume_version_id is None:
        raise TransitionError("Generate a resume before approval.")
    profile = get_profile(db, user)
    posting = db.get(JobPosting, application.job_posting_id)
    assessment = build_assessment(profile, posting)
    if assessment["unknown_count"] and not acknowledge_unverified:
        raise TransitionError("Confirm unverified skills or explicitly acknowledge them before approval.")
    if assessment["not_possessed"] and not acknowledge_gaps:
        raise TransitionError("This job has qualifications you said you do not have. Acknowledge that before approval.")
    application.acknowledge_unverified = acknowledge_unverified
    application.acknowledge_gaps = acknowledge_gaps
    if application.status == "awaiting_skill_verification":
        transition(db, application, "awaiting_review", "User continued with unverified skills acknowledged.")
    if application.status == "preparing":
        transition(db, application, "awaiting_review", "Ready for approval.")
    if application.status != "awaiting_review":
        raise TransitionError("Only applications awaiting review can be approved.")
    now = datetime.now(timezone.utc)
    db.add(
        ApplicationApproval(
            application_id=application.id,
            user_id=user.id,
            draft_version=application.draft_version,
            resume_version_id=application.resume_version_id,
            cover_letter_id=application.cover_letter_id,
            approved_at=now,
        )
    )
    from app.models import ResumeVersion

    version = db.get(ResumeVersion, application.resume_version_id)
    if version is not None:
        version.approved_by_user = True  # approving the application approves this exact resume
    transition(db, application, "approved", "User approved this exact draft and document versions.")
    return application


def submit_application(
    db: Session,
    user: User,
    application: Application,
    *,
    method: str,
    simulate_failure: bool = False,
    defer_sensitive: bool = False,
) -> dict:
    if method not in {"simulated", "manual"}:
        raise TransitionError(
            "No authorized employer submission integration is configured. Use simulated or manual handoff."
        )
    if valid_approval(db, application) is None:
        raise TransitionError("Submission requires a current approval of this draft and its documents.")
    if application.status not in {"approved", "failed"}:
        raise TransitionError("Approve the application before submission.")
    existing = db.scalar(
        select(SubmissionAttempt).where(
            SubmissionAttempt.application_id == application.id,
            SubmissionAttempt.status == "succeeded",
        )
    )
    if existing:
        raise TransitionError("This application already has a recorded submission and was not sent again.")
    # A practice (simulated) submission sends nothing, so blank personal answers do not change it into a hand-off.
    if application.status == "failed":
        invalidate_approval(db, application, "A failed attempt cannot be retried under the old approval.")
        transition(db, application, "awaiting_review", "Review this application again before another attempt.")
        return {
            "status": application.status,
            "is_live_submission": False,
            "confirmation_id": None,
            "method": method,
            "message": "The failed attempt was not submitted. Approve the application again before retrying.",
        }
    transition(db, application, "submitting", f"Starting {method} submission.")
    now = datetime.now(timezone.utc)
    if simulate_failure:
        db.add(
            SubmissionAttempt(
                application_id=application.id,
                user_id=user.id,
                method=method,
                status="failed",
                is_live=False,
                error="Simulated provider failure.",
                created_at=now,
            )
        )
        transition(db, application, "failed", "The submission attempt failed. It was not marked submitted.")
        application.confirmation_id = None
        application.is_live_submission = False
        return {"status": application.status, "is_live_submission": False, "confirmation_id": None, "method": method}
    if method == "manual":
        db.add(
            SubmissionAttempt(
                application_id=application.id,
                user_id=user.id,
                method="manual",
                status="handoff",
                is_live=False,
                created_at=now,
            )
        )
        transition(db, application, "manual_action_required", "Waiting for you to finish the employer form.")
        posting = db.get(JobPosting, application.job_posting_id)
        return {
            "status": application.status,
            "is_live_submission": False,
            "confirmation_id": None,
            "method": "manual",
            "application_url": posting.application_url if posting else None,
            "packet": _packet(db, application),
        }
    confirmation_id = f"sim_{uuid.uuid4().hex[:12]}"
    db.add(
        SubmissionAttempt(
            application_id=application.id,
            user_id=user.id,
            method="simulated",
            status="succeeded",
            is_live=False,
            confirmation_id=confirmation_id,
            created_at=now,
        )
    )
    transition(db, application, "submitted", "Recorded a simulated submission. No employer received this application.")
    application.submission_method = "simulated"
    application.is_live_submission = False
    application.confirmation_id = confirmation_id
    return {
        "status": application.status,
        "is_live_submission": False,
        "confirmation_source": "simulated",
        "confirmation_id": confirmation_id,
        "method": "simulated",
    }


def confirm_manual(db: Session, user: User, application: Application, note: str) -> dict:
    if application.status != "manual_action_required":
        raise TransitionError("Manual confirmation is only available after a handoff.")
    if not note.strip():
        raise TransitionError("Describe how you confirmed the submission.")
    confirmation_id = f"user_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    db.add(
        SubmissionAttempt(
            application_id=application.id,
            user_id=user.id,
            method="manual",
            status="succeeded",
            is_live=False,
            confirmation_id=confirmation_id,
            error=None,
            created_at=now,
        )
    )
    transition(db, application, "submitted", note.strip())
    application.submission_method = "manual"
    application.is_live_submission = False
    application.confirmation_id = confirmation_id
    return {
        "status": "submitted",
        "is_live_submission": False,
        "confirmation_source": "user",
        "confirmation_id": confirmation_id,
        "method": "manual",
    }


def update_status(db: Session, application: Application, status: str, note: str, interview_at: datetime | None) -> None:
    if status not in {"interview", "offer", "rejected", "withdrawn"}:
        raise TransitionError("That status can only be set by the submission workflow.")
    transition(db, application, status, note)
    if interview_at:
        application.interview_at = interview_at


def _packet(db: Session, application: Application) -> dict:
    from app.models import ResumeVersion

    resume = db.get(ResumeVersion, application.resume_version_id) if application.resume_version_id else None
    letter = db.get(CoverLetter, application.cover_letter_id) if application.cover_letter_id else None
    return {
        "resume_text": resume.content_text if resume else "",
        "cover_letter": letter.body if letter else "",
        "answers": [item for item in loads(application.answers_json, []) if not item.get("sensitive") or item.get("answer")],
    }


def replace_answers(db: Session, application: Application, answers: list[dict]) -> None:
    cleaned = []
    for item in answers:
        key = item.get("key")
        if key in SENSITIVE_KEYS:
            # Sensitive answers are stored only when the user typed them. Never invent them.
            cleaned.append(
                {
                    "key": key,
                    "prompt": item.get("prompt") or key,
                    "answer": (item.get("answer") or "").strip(),
                    "sensitive": True,
                    "requires_user": True,
                    "deferred": bool(item.get("deferred")),
                }
            )
        else:
            cleaned.append(item)
    application.answers_json = dumps(cleaned)
    remember_answers(db, application.user_id, cleaned)
    touch_draft(db, application, "Application answers changed, so the previous approval no longer applies.")


def remember_answers(db: Session, user_id: str, answers: list[dict]) -> None:
    from app.models import SavedAnswer

    for item in answers:
        if item.get("key") not in SENSITIVE_KEYS or item["key"] in {"criminal_history", "disability", "demographics"}:
            continue
        value = (item.get("answer") or "").strip()
        if not value:
            continue
        row = db.scalar(select(SavedAnswer).where(SavedAnswer.user_id == user_id, SavedAnswer.question_key == item["key"]))
        if row is None:
            db.add(SavedAnswer(user_id=user_id, question_key=item["key"], answer=value))
        else:
            row.answer = value
