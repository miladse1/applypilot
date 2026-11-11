from typing import TYPE_CHECKING
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:  # type hints only; importing at runtime would be circular
    from app.models.profile import Profile


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    settings: Mapped["UserSettings"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    sessions: Mapped[list["SessionToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSettings(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    job_board_tokens: Mapped[str] = mapped_column(Text, default="[]")
    excluded_employers: Mapped[str] = mapped_column(Text, default="[]")
    min_qualification_score: Mapped[int | None] = mapped_column(nullable=True)
    min_interest_score: Mapped[int | None] = mapped_column(nullable=True)
    # Stored for a future consent system. Unattended submission is not enabled.
    automation_policy: Mapped[str] = mapped_column(Text, default="{}")
    disabled_sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_employers: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"canada": "citizen|permanent_resident|work_permit|study_permit|none", "us": "authorized|needs_sponsorship|not_authorized"}
    work_authorization: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "sonnet" (default) or "opus" for resume rewriting, cover letters, and the assistant.
    ai_quality_model: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Stop calling the AI once estimated spend reaches this many US dollars. Null uses AI_SPEND_LIMIT_USD.
    ai_spend_limit_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Job-site sign-in. The password itself lives in the macOS Keychain, never in this database.
    jobsite_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    jobsite_sign_in: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    jobsite_create_accounts: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Experience York postings are restricted to York co-op students. They are never sent to Claude
    # unless the user confirms York gave permission (off by default).
    york_ai_permission: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    user: Mapped[User] = relationship(back_populates="settings")


class SessionToken(IdMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class PasswordResetToken(IdMixin, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

