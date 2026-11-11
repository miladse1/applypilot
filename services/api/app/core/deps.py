from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import ensure_utc, hash_token, utcnow
from app.models import SessionToken, User


def extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip() or None
    return request.cookies.get("applypilot_session")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw = extract_token(request)
    if not raw:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "Sign in required."})
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(raw)))
    if session is None or session.revoked_at is not None or ensure_utc(session.expires_at) <= utcnow():
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "Session expired."})
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "Account unavailable."})
    return user
