"""Which postings may be sent to an AI service.

Experience York co-op postings are "posted solely for the benefit of qualified and admitted
students in the Program ... Sharing of these postings is strictly prohibited" (York University
Co-op & Internship Program Terms and Conditions), and York's generative AI guidelines say York
data must not be entered into public AI platforms such as Claude. So these postings are
restricted: they are stored only for this user, on this computer, and no part of them (title,
company, description, requirements, or skills derived from them) is sent to Claude, unless the
user confirms York has given permission. Everything else (matching, ranking, project choice,
tailoring by reordering and highlighting, and template cover letters) works locally.
"""

from __future__ import annotations

from sqlalchemy import select

RESTRICTED_SOURCES = {"yorku"}
PRIVATE_NOTE = (
    "This Experience York posting stays on your computer: York's co-op terms prohibit sharing postings, "
    "so it is not sent to Claude."
)
PRIVATE_TITLE = "Private Experience York posting"


def is_restricted(posting) -> bool:
    return bool(posting is not None and (getattr(posting, "restricted", None) or getattr(posting, "source", None) in RESTRICTED_SOURCES))


def york_permission(db, user_id: str | None) -> bool:
    from app.models import UserSettings

    if db is None or not user_id:
        return False
    row = db.scalar(select(UserSettings).where(UserSettings.user_id == user_id))
    return bool(row and row.york_ai_permission)


def ai_allowed(db, user_id: str | None, posting) -> bool:
    """True when this posting's content may be sent to Claude."""
    if not is_restricted(posting):
        return True
    return york_permission(db, user_id)
