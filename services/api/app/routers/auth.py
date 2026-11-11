from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import extract_token, get_current_user
from app.core.ratelimit import limiter
from app.core.security import ensure_utc, expiry_from_now, hash_password, hash_token, new_token, utcnow, verify_password
from app.models import JobPreferences, PasswordResetToken, Profile, SessionToken, User, UserSettings
from app.routers.common import error
from app.services.profile_ops import export_user, serialize_profile, snapshot_profile

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Rate limits (per client address; behind the web app's proxy that is the whole installation).
LOGIN_FAILURES_PER_ACCOUNT = 20  # per 10 minutes, per address and email
LOGIN_FAILURES_PER_CLIENT = 50  # per 10 minutes, per address, across all emails
REGISTRATIONS_PER_HOUR = 10
RESET_REQUESTS_PER_CLIENT_PER_HOUR = 10
_TEN_MINUTES = 600
_HOUR = 3600
_dummy_hash: str | None = None


def _client(request: Request) -> str:
    return request.client.host if request.client else "local"


def _equalize_timing(password: str) -> None:
    """Spend the same time on an unknown email as on a wrong password, so timing does not reveal accounts."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(new_token())
    verify_password(password, _dummy_hash)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    # Long inputs are refused before the deliberately slow password hash runs.
    password: str = Field(min_length=1, max_length=200)


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


def _issue_session(db: Session, user: User) -> str:
    raw = new_token()
    db.add(
        SessionToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=expiry_from_now(),
            created_at=utcnow(),
        )
    )
    db.commit()
    return raw


def _public_user(user: User, profile: Profile) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "profile": serialize_profile(profile),
    }


@router.post("/register", status_code=201)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if not get_settings().allow_registration and db.scalar(select(User.id).limit(1)) is not None:
        raise error(403, "registration_closed", "This ApplyPilot already has an account. Sign in instead, or set ALLOW_REGISTRATION=true to add another.")
    if not limiter.hit(f"register:{_client(request)}", REGISTRATIONS_PER_HOUR, _HOUR):
        raise error(429, "rate_limited", "Too many new accounts from this computer. Try again later.")
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise error(409, "email_taken", "An account with that email already exists.")
    user = User(email=email, password_hash=hash_password(payload.password), full_name=payload.full_name.strip())
    profile = Profile(user=user)
    profile.preferences = JobPreferences()
    user.settings = UserSettings()
    db.add(user)
    db.flush()
    snapshot_profile(db, profile)
    db.commit()
    db.refresh(user)
    token = _issue_session(db, user)
    return {"session_token": token, "user": _public_user(user, profile)}


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = payload.email.lower()
    client = _client(request)
    account_key = f"login-fail:{client}:{email}"
    client_key = f"login-fail:{client}"
    if limiter.count(account_key, _TEN_MINUTES) >= LOGIN_FAILURES_PER_ACCOUNT or limiter.count(client_key, _TEN_MINUTES) >= LOGIN_FAILURES_PER_CLIENT:
        raise error(429, "rate_limited", "Too many sign-in attempts. Try again later.")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        _equalize_timing(payload.password)
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        limiter.hit(account_key, LOGIN_FAILURES_PER_ACCOUNT, _TEN_MINUTES)
        limiter.hit(client_key, LOGIN_FAILURES_PER_CLIENT, _TEN_MINUTES)
        raise error(401, "invalid_credentials", "Email or password is incorrect.")
    limiter.clear(account_key)
    token = _issue_session(db, user)
    return {"session_token": token, "user": _public_user(user, user.profile)}


@router.post("/logout")
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    header = request.headers.get("authorization", "")
    raw = header.split(" ", 1)[1].strip() if header.lower().startswith("bearer ") else request.cookies.get("applypilot_session")
    if raw:
        session = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(raw)))
        if session and session.user_id == user.id:
            session.revoked_at = utcnow()
            db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _public_user(user, user.profile)


RESET_MESSAGE = "If an account exists for that email, we sent a link to reset the password. Check your inbox and spam folder."
RESET_LIMIT_PER_HOUR = 3


@router.post("/password-reset/request")
def request_reset(payload: ResetRequestIn, request: Request, db: Session = Depends(get_db)):
    """Email a single-use reset link. The response is the same whether or not the account exists."""
    import logging

    from app.services.email import EmailError, password_reset_email, send_email

    log = logging.getLogger("applypilot.auth")
    settings = get_settings()
    if not limiter.hit(f"reset:{_client(request)}", RESET_REQUESTS_PER_CLIENT_PER_HOUR, _HOUR):
        log.warning("Password reset requests from one address reached the hourly limit.")
        return {"message": RESET_MESSAGE}
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not user.is_active:
        return {"message": RESET_MESSAGE}
    now = utcnow()
    recent = db.scalars(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.created_at >= now - timedelta(hours=1))
    ).all()
    if len(recent) >= RESET_LIMIT_PER_HOUR:
        log.warning("Password reset rate limit reached for a user account.")
        return {"message": RESET_MESSAGE}
    # Only the newest link works.
    for older in db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))).all():
        older.used_at = now
    raw = new_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=now + timedelta(minutes=settings.password_reset_minutes),
            created_at=now,
        )
    )
    db.commit()
    # The token travels in the URL fragment, so it never reaches server logs or referrer headers.
    link = f"{settings.app_base_url.rstrip('/')}/reset-password#token={raw}"
    subject, text, html = password_reset_email(user.full_name.split(" ")[0] or "there", link, settings.password_reset_minutes)
    if settings.email_configured:
        try:
            send_email(user.email, subject, text, html, settings)
        except EmailError as exc:
            log.error("Password reset email failed: %s", exc)
    elif settings.is_production:
        log.error("Password reset requested, but SMTP is not configured. No email was sent.")
    else:
        # Development only: the link goes to the API console, never to the browser.
        log.warning("Email is not configured. Development reset link for %s: %s", user.email, link)
    return {"message": RESET_MESSAGE}


@router.post("/password-reset/confirm")
def confirm_reset(payload: ResetConfirmIn, db: Session = Depends(get_db)):
    record = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(payload.token.strip())))
    if record is None or record.used_at is not None or ensure_utc(record.expires_at) <= utcnow():
        raise error(400, "invalid_token", "This reset link is invalid, already used, or expired. Request a new one.")
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise error(400, "invalid_token", "This reset link is invalid, already used, or expired. Request a new one.")
    user.password_hash = hash_password(payload.password)
    now = utcnow()
    record.used_at = now
    for other in db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))).all():
        other.used_at = now
    # Sign out everywhere: whoever had access before the reset loses it.
    for session in user.sessions:
        if session.revoked_at is None:
            session.revoked_at = now
    db.commit()
    return {"ok": True}


@router.post("/password-change")
def change_password(payload: PasswordChangeIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise error(401, "invalid_credentials", "Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    # Sign out every other session; the one making this change stays signed in.
    current = extract_token(request)
    current_hash = hash_token(current) if current else None
    now = utcnow()
    for session in user.sessions:
        if session.revoked_at is None and session.token_hash != current_hash:
            session.revoked_at = now
    db.commit()
    return {"ok": True}


@router.get("/export")
def export_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return export_user(db, user)


@router.delete("/account")
def delete_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import shutil
    from pathlib import Path

    folder = Path(get_settings().storage_path) / user.id
    if folder.exists():
        shutil.rmtree(folder)
    db.delete(user)
    db.commit()
    return {"ok": True}
