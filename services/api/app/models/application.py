from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Application(IdMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "active_slot", name="uq_active_application"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_posting_id: Mapped[str] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    # job_posting_id while the application is active; null after withdraw/reject so a reapply is allowed.
    active_slot: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="preparing", index=True)
    draft_version: Mapped[int] = mapped_column(Integer, default=1)
    profile_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resume_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cover_letter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    answers_json: Mapped[str] = mapped_column(Text, default="[]")
    notes: Mapped[str] = mapped_column(Text, default="")
    submission_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_live_submission: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acknowledge_unverified: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledge_gaps: Mapped[bool] = mapped_column(Boolean, default=False)
    interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the posting also has to be submitted on a university portal (Experience York) or LinkedIn
    # Easy Apply, the date the user marked that part as done. The employer-site part is the status.
    portal_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApplicationApproval(IdMixin, Base):
    __tablename__ = "application_approvals"

    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    draft_version: Mapped[int] = mapped_column(Integer)
    resume_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cover_letter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SubmissionAttempt(IdMixin, Base):
    __tablename__ = "submission_attempts"

    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplicationStatusEvent(IdMixin, Base):
    __tablename__ = "application_status_history"

    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SavedAnswer(IdMixin, TimestampMixin, Base):
    __tablename__ = "saved_answers"
    __table_args__ = (UniqueConstraint("user_id", "question_key", name="uq_saved_answer"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question_key: Mapped[str] = mapped_column(String(80))
    answer: Mapped[str] = mapped_column(Text)


class CareerPlan(IdMixin, TimestampMixin, Base):
    __tablename__ = "career_plans"
    __table_args__ = (UniqueConstraint("user_id", "normalized_name", name="uq_career_plan"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    normalized_name: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="interested")
    frequency: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")


class Notification(IdMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActivityLog(IdMixin, Base):
    __tablename__ = "activity_logs"

    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssistantConversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "assistant_conversations"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")


class AssistantMessage(IdMixin, Base):
    """One turn. `content_json` holds the provider's content blocks unchanged so they can be replayed."""

    __tablename__ = "assistant_messages"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content_json: Mapped[str] = mapped_column(Text, default="[]")
    display_text: Mapped[str] = mapped_column(Text, default="")
    actions_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AIUsage(IdMixin, Base):
    """One model request: tokens and estimated cost, for the spend dashboard and the spending limit."""

    __tablename__ = "ai_usage"

    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    feature: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AICache(IdMixin, Base):
    """Results of structured requests, keyed by a hash of the model and the full request, so identical work is not paid for twice."""

    __tablename__ = "ai_cache"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    feature: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    result_json: Mapped[str] = mapped_column(Text)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplyRun(IdMixin, Base):
    """One browser-assisted attempt to fill in and submit an approved application.

    `submitted` is set only after the employer's confirmation page was seen; the page text,
    URL, and a screenshot are kept as evidence.
    """

    __tablename__ = "apply_runs"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(30), default="generic")
    # queued, running, needs_you, submitted, unconfirmed, failed, cancelled, handed_off, interrupted
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    submit_mode: Mapped[str] = mapped_column(String(10), default="auto")
    # login, captcha, verification, questions, review, blocked, unconfirmed, error
    attention: Mapped[str | None] = mapped_column(String(30), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    questions_json: Mapped[str] = mapped_column(Text, default="[]")
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    page_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    filled_count: Mapped[int] = mapped_column(Integer, default=0)
    # What was entered (label, value, source) and which documents were attached, for review.
    filled_json: Mapped[str] = mapped_column(Text, default="[]")
    documents_json: Mapped[str] = mapped_column(Text, default="[]")
    submit_clicked: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SiteAccount(IdMixin, Base):
    """An employer job site where ApplyPilot signed in or created an account for the user."""

    __tablename__ = "site_accounts"
    __table_args__ = (UniqueConstraint("user_id", "host", name="uq_site_account"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    host: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    created_by_applypilot: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PortalPosting(IdMixin, TimestampMixin, Base):
    """A posting saved from a site the user signs in to (Experience York) or browses (LinkedIn).

    Keeps the original link and how the employer wants applications, so an application that
    must be submitted on the portal and on the employer's website is tracked as both.
    """

    __tablename__ = "portal_postings"
    __table_args__ = (UniqueConstraint("user_id", "portal", "external_id", name="uq_portal_posting"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    portal: Mapped[str] = mapped_column(String(40))  # york, linkedin, web
    external_id: Mapped[str] = mapped_column(String(160))
    job_posting_id: Mapped[str] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    application_method: Mapped[str | None] = mapped_column(String(400), nullable=True)
    employer_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(120), nullable=True)
    documents: Mapped[str | None] = mapped_column(Text, nullable=True)
    term: Mapped[str | None] = mapped_column(String(120), nullable=True)
    easy_apply: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
