"""Database side of browser-assisted applications: creating runs and recording what happened."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, ApplyRun, JobPosting, Notification, SavedAnswer, SubmissionAttempt, User
from app.services.applications import TransitionError, transition, valid_approval
from app.services.autoapply.driver import SUPPORT, detect_platform
from app.services.jsonutil import dumps, loads

ACTIVE = {"queued", "running", "needs_you"}
FINAL = {"submitted", "failed", "cancelled", "handed_off", "interrupted"}
# Answers to these questions also become general facts, so other wordings of them are answered too.
GENERAL_KEYS = {"country", "location", "city", "province", "postal_code", "address_line1", "how_heard", "salary", "age_18", "linkedin", "github", "website", "start_date", "graduation"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def support_for(posting: JobPosting | None) -> dict:
    from app.services.job_enrich import restricted_platform

    if posting is None or not posting.application_url:
        return {"platform": None, "level": "none", "note": "This posting has no application link."}
    if posting.is_sample:
        return {"platform": None, "level": "none", "note": "Practice listings cannot be sent to an employer."}
    restricted = restricted_platform(posting.application_url)
    if restricted:
        return {"platform": None, "level": "none", "note": f"{restricted} does not allow automated applications. Apply there yourself."}
    platform = detect_platform(posting.application_url)
    level, note = SUPPORT[platform]
    return {"platform": platform, "level": level, "note": note}


def create_runs(db: Session, user: User, application_ids: list[str], submit_mode: str) -> dict:
    if submit_mode not in {"auto", "review"}:
        raise TransitionError("Choose whether ApplyPilot submits for you or stops for your review.")
    batch_id = str(uuid.uuid4())
    created, skipped = [], []
    for application_id in dict.fromkeys(application_ids):
        application = db.get(Application, application_id)
        if application is None or application.user_id != user.id:
            continue
        posting = db.get(JobPosting, application.job_posting_id)
        title = f"{posting.title} at {posting.company}" if posting else "Application"
        support = support_for(posting)
        active = db.scalar(select(ApplyRun).where(ApplyRun.application_id == application.id, ApplyRun.status.in_(ACTIVE)))
        if active:
            skipped.append({"application_id": application.id, "title": title, "reason": "ApplyPilot is already working on this one."})
        elif support["level"] == "none":
            skipped.append({"application_id": application.id, "title": title, "reason": support["note"]})
        elif application.status != "approved" or valid_approval(db, application) is None:
            skipped.append({"application_id": application.id, "title": title, "reason": "Approve the current draft first."})
        else:
            run = ApplyRun(user_id=user.id, application_id=application.id, batch_id=batch_id, platform=support["platform"], status="queued", submit_mode=submit_mode, created_at=now(), updated_at=now())
            db.add(run)
            db.flush()
            created.append(run.id)
    return {"batch_id": batch_id, "created": created, "skipped": skipped}


def event(run: ApplyRun, message: str) -> None:
    events = loads(run.events_json, [])
    events.append({"at": now().isoformat(), "message": message})
    run.events_json = dumps(events[-60:])
    run.updated_at = now()


def start(db: Session, run: ApplyRun) -> str | None:
    """Move the application into `submitting`. Returns a reason when the run cannot start."""
    application = db.get(Application, run.application_id)
    if application is None:
        return "The application no longer exists."
    if application.status == "approved" and valid_approval(db, application) is not None:
        transition(db, application, "submitting", "ApplyPilot started filling in the employer's form.")
    elif application.status != "submitting":
        return "This application is no longer approved, so ApplyPilot did not open it."
    run.status = "running"
    run.attention = None
    run.message = ""
    event(run, "Started.")
    return None


def _save(db: Session, user_id: str, key: str, value: str) -> None:
    row = db.scalar(select(SavedAnswer).where(SavedAnswer.user_id == user_id, SavedAnswer.question_key == key[:80]))
    if row is None:
        db.add(SavedAnswer(user_id=user_id, question_key=key[:80], answer=value))
    else:
        row.answer = value


def review_changes(questions: list[dict], answers: dict[str, str], filled: list[dict] | None = None) -> tuple[list[str], list[str]]:
    """(keys the user reviewed, keys whose answer they changed, including edits made at the final review)."""
    reviewed, corrected = [], []
    asked = {question["key"] for question in questions}
    for entry in filled or []:
        key = entry.get("key")
        value = (answers.get(key) or "").strip() if key else ""
        if key and key not in asked and value and value != (entry.get("value") or "").strip():
            corrected.append(key)
    for question in questions:
        key = question["key"]
        value = (answers.get(key) or "").strip()
        if question.get("status") != "drafted" or not value:
            continue
        reviewed.append(key)
        if value != (question.get("draft") or "").strip():
            corrected.append(key)
    return reviewed, corrected


def remember(db: Session, user_id: str, questions: list[dict], answers: dict[str, str], filled: list[dict] | None = None) -> None:
    by_key = {item["key"]: item for item in questions}
    # Edits at the final review count as corrections of what ApplyPilot entered.
    for entry in filled or []:
        if entry.get("key") and entry["key"] not in by_key and entry.get("source") != "approved_document":
            by_key[entry["key"]] = {
                "key": entry["key"], "label": entry.get("label"), "status": "drafted", "draft": entry.get("value") or "",
                "remember": entry.get("kind") != "textarea" and len(entry.get("value") or "") <= 120,
            }
    for key, value in answers.items():
        value = (value or "").strip()
        question = by_key.get(key)
        if not value or question is None:
            continue
        if not question.get("remember"):
            # Long answers are specific to one job, but a correction shows how the user wants to answer:
            # it is kept as an example for future drafts.
            if question.get("status") == "drafted" and value != (question.get("draft") or "").strip():
                _save(db, user_id, "ex:" + key[2:], value)
            continue
        keys = [key]
        category = question.get("category")
        if category in GENERAL_KEYS:
            keys.append(category)
        if category in {"eeo_gender", "eeo_race", "eeo_veteran", "eeo_disability"} and re.search(r"decline|prefer not|don.?t wish|not to", value, re.I):
            keys.append("voluntary_disclosures")
            value_for = {"voluntary_disclosures": "decline"}
        else:
            value_for = {}
        if category == "privacy_consent" and re.match(r"^(yes|true|i agree|agree|accept)", value, re.I):
            keys.append("consent_privacy")
            value_for["consent_privacy"] = "yes"
        for saved_key in keys:
            _save(db, user_id, saved_key, value_for.get(saved_key, value))


def _notify(db: Session, user_id: str, title: str, body: str) -> None:
    db.add(Notification(user_id=user_id, title=title, body=body, created_at=now()))


def finish_submitted(db: Session, run: ApplyRun, confirmation_text: str, confirmation_url: str, screenshot: str | None) -> None:
    application = db.get(Application, run.application_id)
    posting = db.get(JobPosting, application.job_posting_id)
    match = re.search(r"(?:application|reference|confirmation)\s*(?:id|number|#)\s*[:#]?\s*([A-Z0-9-]{5,})", confirmation_text, re.I)
    confirmation_id = match.group(1) if match else "page-" + hashlib.sha256(f"{confirmation_url}|{confirmation_text}".encode()).hexdigest()[:12]
    db.add(SubmissionAttempt(application_id=application.id, user_id=run.user_id, method="browser", status="succeeded", is_live=True, confirmation_id=confirmation_id, created_at=now()))
    if application.status == "submitting":
        transition(db, application, "submitted", f"Submitted by ApplyPilot. The employer's page said: {confirmation_text[:300]}")
    application.submission_method = "browser"
    application.is_live_submission = True
    application.confirmation_id = confirmation_id
    run.status = "submitted"
    run.attention = None
    run.message = "Submitted. The employer's confirmation page was captured."
    run.confirmation_text = confirmation_text[:2000]
    run.confirmation_url = confirmation_url[:1000]
    run.screenshot_path = screenshot
    run.finished_at = now()
    event(run, "Submitted and confirmed.")
    _notify(db, run.user_id, "Application submitted", f"{posting.title} at {posting.company}: the employer's confirmation page was captured.")


def finish_failed(db: Session, run: ApplyRun, message: str) -> None:
    application = db.get(Application, run.application_id)
    db.add(SubmissionAttempt(application_id=application.id, user_id=run.user_id, method="browser", status="failed", is_live=False, error=message[:1000], created_at=now()))
    if application.status == "submitting":
        transition(db, application, "failed", message[:500])
    run.status = "failed"
    run.message = message
    run.finished_at = now()
    event(run, message)


def stop(db: Session, run: ApplyRun, status: str, message: str) -> None:
    """End a run without a confirmed submission: cancelled, handed off, or interrupted."""
    application = db.get(Application, run.application_id)
    if application is not None and application.status == "submitting":
        if run.submit_clicked or status == "handed_off":
            # Something may have been sent, or the user is finishing it: confirm it yourself afterwards.
            transition(db, application, "manual_action_required", message[:500])
        else:
            transition(db, application, "approved", "Nothing was sent. " + message[:400])
    run.status = status
    run.message = message
    run.finished_at = now()
    event(run, message)


def confirm_by_user(db: Session, run: ApplyRun, note: str) -> None:
    """After an unconfirmed submit, the user saw the confirmation themselves (for example, by email)."""
    application = db.get(Application, run.application_id)
    if application.status not in {"submitting", "manual_action_required"}:
        raise TransitionError("This application is not waiting for a confirmation.")
    confirmation_id = f"user_{uuid.uuid4().hex[:12]}"
    db.add(SubmissionAttempt(application_id=application.id, user_id=run.user_id, method="browser", status="succeeded", is_live=False, confirmation_id=confirmation_id, created_at=now()))
    transition(db, application, "submitted", note or "You confirmed that ApplyPilot's submission went through.")
    application.submission_method = "browser"
    application.is_live_submission = False
    application.confirmation_id = confirmation_id
    run.status = "submitted"
    run.attention = None
    run.message = "You confirmed this submission."
    run.finished_at = now()
    event(run, "You confirmed the submission.")


def recover(db: Session) -> int:
    """After a restart the browser tabs are gone. Close out runs that were in progress."""
    rows = db.scalars(select(ApplyRun).where(ApplyRun.status.in_(ACTIVE))).all()
    for run in rows:
        if run.submit_clicked:
            run.attention = "unconfirmed"
            stop(db, run, "interrupted", "ApplyPilot restarted after clicking Submit. Check your email or the employer's site, then confirm it here.")
        else:
            stop(db, run, "interrupted", "ApplyPilot restarted before this application was sent. Start it again when you are ready.")
    return len(rows)


def run_out(db: Session, run: ApplyRun) -> dict:
    application = db.get(Application, run.application_id)
    posting = db.get(JobPosting, application.job_posting_id) if application else None
    return {
        "id": run.id,
        "application_id": run.application_id,
        "batch_id": run.batch_id,
        "title": posting.title if posting else None,
        "company": posting.company if posting else None,
        "platform": run.platform,
        "status": run.status,
        "submit_mode": run.submit_mode,
        "attention": run.attention,
        "message": run.message,
        "questions": loads(run.questions_json, []),
        "events": loads(run.events_json, [])[-12:],
        "filled_count": run.filled_count,
        "filled": loads(run.filled_json, []),
        "documents": loads(run.documents_json, []),
        "submit_clicked": run.submit_clicked,
        "confirmation_text": run.confirmation_text,
        "confirmation_url": run.confirmation_url,
        "has_screenshot": bool(run.screenshot_path),
        "application_status": application.status if application else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
