"""Job-site sign-in for browser-assisted applications.

The user saves one email and password for employer job sites (Workday and similar). The
password is kept in the macOS Keychain under "ApplyPilot job sites" and read only at the
moment a sign-in form is filled. It is never stored in the database, logged, or sent to a
model. Creating accounts is a separate opt-in, because it accepts the site's account terms.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import SiteAccount, User, UserSettings

SERVICE = "ApplyPilot job sites"


class KeychainUnavailable(Exception):
    pass


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
    except ImportError as exc:  # pragma: no cover
        raise KeychainUnavailable("The keyring package is not installed.") from exc
    if isinstance(keyring.get_keyring(), fail.Keyring):
        raise KeychainUnavailable("No system keychain is available on this computer.")
    return keyring


def save_password(user_id: str, password: str) -> None:
    _keyring().set_password(SERVICE, user_id, password)


def delete_password(user_id: str) -> None:
    keyring = _keyring()
    try:
        keyring.delete_password(SERVICE, user_id)
    except Exception:  # noqa: BLE001 - nothing saved yet
        pass


def has_password(user_id: str) -> bool:
    try:
        return bool(_keyring().get_password(SERVICE, user_id))
    except KeychainUnavailable:
        return False


class Accounts:
    """What the driver uses during a run. Reads the password only when asked."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        with SessionLocal() as db:
            row = db.scalar(select(UserSettings).where(UserSettings.user_id == user_id))
            user = db.get(User, user_id)
            self.email = (row.jobsite_email if row and row.jobsite_email else user.email) if user else None
            self.sign_in = bool(row and row.jobsite_sign_in)
            self.allow_create = bool(row and row.jobsite_sign_in and row.jobsite_create_accounts)

    def credentials(self) -> tuple[str, str] | None:
        if not self.sign_in or not self.email:
            return None
        try:
            password = _keyring().get_password(SERVICE, self.user_id)
        except KeychainUnavailable:
            return None
        return (self.email, password) if password else None

    def record(self, host: str, *, created: bool) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            row = db.scalar(select(SiteAccount).where(SiteAccount.user_id == self.user_id, SiteAccount.host == host))
            if row is None:
                db.add(SiteAccount(user_id=self.user_id, host=host, email=self.email or "", created_by_applypilot=created, created_at=now, last_used_at=now))
            else:
                row.last_used_at = now
                row.created_by_applypilot = row.created_by_applypilot or created
            db.commit()
