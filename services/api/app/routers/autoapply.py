"""Browser-assisted applications: queue approved applications, answer what ApplyPilot asks, and track results."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Application, ApplyRun, JobPosting, SavedAnswer, User
from app.routers.common import error, not_found
from app.services.applications import TransitionError, valid_approval
from app.services.autoapply import records
from app.services.jsonutil import dumps, loads

router = APIRouter(prefix="/api/v1/apply", tags=["apply"])


class RunsIn(BaseModel):
    application_ids: list[str] = Field(min_length=1, max_length=50)
    submit_mode: str = "auto"


class AnswersIn(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class ConfirmIn(BaseModel):
    note: str = ""


class SavedIn(BaseModel):
    values: dict[str, str]


class AccountIn(BaseModel):
    email: str | None = None
    password: str | None = Field(default=None, max_length=200)
    sign_in: bool | None = None
    create_accounts: bool | None = None


# Preferences that save ApplyPilot from asking the same thing on every form.
PREFERENCE_KEYS = {
    "voluntary_disclosures": "Voluntary questions (gender, ethnicity, veteran, disability): set to “decline” to always choose “I don't wish to answer”.",
    "consent_privacy": "Set to “yes” to accept an employer's candidate privacy notice when a form requires it.",
    "how_heard": "How you heard about a job (for example “Company website”).",
    "location": "Where you live, for example “Toronto, ON, Canada”.",
    "country": "Country of residence.",
    "address_line1": "Street address, for forms that require one.",
    "postal_code": "Postal code.",
    "age_18": "Are you at least 18? (Yes or No)",
    "work_authorization": "Authorized to work in the job's country? (Yes or No)",
    "sponsorship": "Need visa sponsorship? (Yes or No)",
    "start_date": "When you can start.",
    "relocation": "Willing to relocate? (Yes or No)",
    "salary": "Salary expectation, if you want ApplyPilot to give one.",
}


def _owned_run(db: Session, user: User, run_id: str) -> ApplyRun:
    run = db.get(ApplyRun, run_id)
    if run is None or run.user_id != user.id:
        raise not_found()
    return run


def _runner():
    from app.services.autoapply.runner import RUNNER

    return RUNNER


@router.get("/support")
def support(application_ids: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = []
    for application_id in [item for item in application_ids.split(",") if item][:100]:
        application = db.get(Application, application_id)
        if application is None or application.user_id != user.id:
            continue
        out.append({"application_id": application.id, **records.support_for(db.get(JobPosting, application.job_posting_id))})
    return out


@router.post("/runs", status_code=201)
def create(payload: RunsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not get_settings().autoapply_enabled:
        raise error(403, "autoapply_disabled", "Browser-assisted applications are turned off on this server.")
    try:
        result = records.create_runs(db, user, payload.application_ids, payload.submit_mode)
    except TransitionError as exc:
        raise error(400, "invalid_mode", str(exc)) from exc
    db.commit()
    if result["created"]:
        _runner().send("wake")
    return {**result, "runs": [records.run_out(db, db.get(ApplyRun, run_id)) for run_id in result["created"]]}


@router.get("/runs")
def list_runs(scope: str = "recent", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(ApplyRun).where(ApplyRun.user_id == user.id).order_by(ApplyRun.created_at.desc())
    if scope == "active":
        stmt = stmt.where(ApplyRun.status.in_(records.ACTIVE))
    elif scope == "recent":
        since = datetime.now(timezone.utc) - timedelta(days=14)
        stmt = stmt.where((ApplyRun.status.in_(records.ACTIVE)) | (ApplyRun.created_at >= since))
    runs = db.scalars(stmt.limit(100)).all()
    runner = _runner()
    return {
        "runner": runner.status,
        "runs": [{**records.run_out(db, run), "tab_open": runner.attached(run.id)} for run in runs],
        "counts": {
            "active": sum(1 for run in runs if run.status in records.ACTIVE),
            "needs_you": sum(1 for run in runs if run.status == "needs_you"),
        },
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _owned_run(db, user, run_id)
    return {**records.run_out(db, run), "events": loads(run.events_json, []), "tab_open": _runner().attached(run.id)}


@router.post("/runs/{run_id}/continue")
def continue_run(run_id: str, payload: AnswersIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _owned_run(db, user, run_id)
    if run.status != "needs_you":
        raise error(409, "not_waiting", "This application is not waiting for you.")
    answers = {key: value for key, value in payload.answers.items() if isinstance(value, str) and value.strip()}
    questions = loads(run.questions_json, [])
    filled = loads(run.filled_json, [])
    reviewed, corrected = records.review_changes(questions, answers, filled)
    if answers:
        stored = loads(run.answers_json, {})
        stored.update(answers)
        run.answers_json = dumps(stored)
        records.remember(db, user.id, questions, answers, filled)
        typed = len(answers) - len(reviewed)
        parts = [f"approved {len(reviewed) - len(corrected)} drafted answer(s)"] if reviewed else []
        if corrected:
            parts.append(f"corrected {len(corrected)}")
        if typed:
            parts.append(f"answered {typed} question(s)")
        records.event(run, "You " + ", ".join(parts) + ".")
    db.commit()
    _runner().send("continue", run.id, {"approved": reviewed, "corrected": corrected})
    return records.run_out(db, run)


@router.post("/runs/{run_id}/submit-now")
def submit_now(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _owned_run(db, user, run_id)
    if run.status != "needs_you" or run.attention != "review":
        raise error(409, "not_ready", "This application is not waiting for your review.")
    application = db.get(Application, run.application_id)
    if valid_approval(db, application) is None:
        raise error(409, "approval_changed", "The approval for this application changed. Review and approve it again.")
    records.event(run, "You asked ApplyPilot to submit after reviewing the page.")
    db.commit()
    _runner().send("submit_now", run.id)
    return records.run_out(db, run)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _owned_run(db, user, run_id)
    if run.status in records.FINAL:
        raise error(409, "finished", "This run has already finished.")
    if not _runner().attached(run.id):
        records.stop(db, run, "cancelled", "Cancelled. Nothing was sent." if not run.submit_clicked else "Cancelled after ApplyPilot clicked Submit. Check whether it went through.")
        db.commit()
    else:
        _runner().send("cancel", run.id)
    return records.run_out(db, run)


@router.post("/runs/{run_id}/handoff")
def handoff(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _owned_run(db, user, run_id)
    if run.status not in records.ACTIVE:
        raise error(409, "finished", "This run has already finished.")
    if not _runner().attached(run.id):
        records.stop(db, run, "handed_off", "You are finishing this one yourself. Mark it as submitted when you are done.")
        db.commit()
    else:
        _runner().send("handoff", run.id)
    return records.run_out(db, run)


@router.post("/runs/{run_id}/show")
def show(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _owned_run(db, user, run_id)
    _runner().send("show", run.id)
    return {"ok": True, "tab_open": _runner().attached(run.id)}


@router.post("/runs/{run_id}/confirm")
def confirm(run_id: str, payload: ConfirmIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The user checked that a submission went through (for example, a confirmation email arrived)."""
    run = _owned_run(db, user, run_id)
    if not run.submit_clicked and run.status != "handed_off":
        raise error(409, "nothing_sent", "ApplyPilot never clicked Submit on this one, so there is nothing to confirm.")
    try:
        records.confirm_by_user(db, run, payload.note.strip())
    except TransitionError as exc:
        raise error(409, "invalid_transition", str(exc)) from exc
    db.commit()
    _runner().send("cancel", run.id) if _runner().attached(run.id) else None
    return records.run_out(db, run)


@router.post("/runs/{run_id}/retry", status_code=201)
def retry(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _owned_run(db, user, run_id)
    if run.status not in {"failed", "cancelled", "interrupted"}:
        raise error(409, "not_retryable", "Only stopped runs can be started again.")
    result = records.create_runs(db, user, [run.application_id], run.submit_mode)
    if not result["created"]:
        raise error(409, "not_ready", result["skipped"][0]["reason"] if result["skipped"] else "This application cannot be started again.")
    db.commit()
    _runner().send("wake")
    return records.run_out(db, db.get(ApplyRun, result["created"][0]))


@router.get("/runs/{run_id}/screenshot")
def screenshot(run_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = _owned_run(db, user, run_id)
    if not run.screenshot_path or not Path(run.screenshot_path).exists():
        raise not_found()
    return FileResponse(run.screenshot_path, media_type="image/png")


@router.get("/answers")
def saved_answers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = {row.question_key: row.answer for row in db.scalars(select(SavedAnswer).where(SavedAnswer.user_id == user.id)).all()}
    return {
        "preferences": [{"key": key, "description": description, "value": rows.get(key, "")} for key, description in PREFERENCE_KEYS.items()],
        "questions": [{"key": key, "question": key[2:].replace("-", " "), "value": value} for key, value in sorted(rows.items()) if key.startswith("q:")],
    }


@router.put("/answers")
def save_answers(payload: SavedIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for key, value in payload.values.items():
        if key not in PREFERENCE_KEYS and not key.startswith("q:"):
            continue
        row = db.scalar(select(SavedAnswer).where(SavedAnswer.user_id == user.id, SavedAnswer.question_key == key[:80]))
        value = (value or "").strip()
        if not value:
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            db.add(SavedAnswer(user_id=user.id, question_key=key[:80], answer=value))
        else:
            row.answer = value
    db.commit()
    return saved_answers(user, db)


def _account_out(db: Session, user: User) -> dict:
    from app.models import SiteAccount
    from app.services.autoapply.accounts import KeychainUnavailable, _keyring, has_password

    row = user.settings
    try:
        _keyring()
        keychain = True
    except KeychainUnavailable:
        keychain = False
    sites = db.scalars(select(SiteAccount).where(SiteAccount.user_id == user.id).order_by(SiteAccount.last_used_at.desc())).all()
    return {
        "email": (row.jobsite_email if row and row.jobsite_email else user.email),
        "has_password": has_password(user.id),
        "sign_in": bool(row and row.jobsite_sign_in),
        "create_accounts": bool(row and row.jobsite_create_accounts),
        "keychain_available": keychain,
        "sites": [{"host": site.host, "email": site.email, "created_by_applypilot": site.created_by_applypilot, "last_used_at": site.last_used_at.isoformat() if site.last_used_at else None} for site in sites],
    }


@router.get("/account")
def read_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _account_out(db, user)


@router.put("/account")
def write_account(payload: AccountIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Save the job-site email, password (to the Keychain), and what ApplyPilot may do with them."""
    from app.services.autoapply.accounts import KeychainUnavailable, delete_password, save_password

    row = user.settings
    data = payload.model_dump(exclude_unset=True)
    if "email" in data:
        email = (data["email"] or "").strip()
        if email and "@" not in email:
            raise error(400, "invalid_email", "Enter the email you use on job sites.")
        row.jobsite_email = email or None
    if "password" in data:
        try:
            if data["password"]:
                save_password(user.id, data["password"])
            else:
                delete_password(user.id)
                row.jobsite_sign_in = False
        except KeychainUnavailable as exc:
            raise error(400, "keychain_unavailable", str(exc)) from exc
    if "sign_in" in data:
        row.jobsite_sign_in = bool(data["sign_in"])
    if "create_accounts" in data:
        row.jobsite_create_accounts = bool(data["create_accounts"])
    db.commit()
    db.refresh(user)
    return _account_out(db, user)
