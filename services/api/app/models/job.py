from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class JobPosting(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_postings"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_external"),)

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(240))
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location: Mapped[str | None] = mapped_column(String(240), nullable=True)
    work_arrangement: Mapped[str] = mapped_column(String(40), default="unknown")
    employment_type: Mapped[str] = mapped_column(String(40), default="unknown")
    seniority: Mapped[str | None] = mapped_column(String(40), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    responsibilities: Mapped[str] = mapped_column(Text, default="")
    application_url: Mapped[str | None] = mapped_column(String(800), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_payload: Mapped[str] = mapped_column(Text, default="{}")
    # Relevance classification (see app.services.taxonomy). Nullable so older rows stay valid.
    role_family: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    role_families: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_scope: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    experience_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    employer_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    also_seen_on: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_detail: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Restricted postings (Experience York) stay private to the user and are never sent to AI services
    # without permission. They are never merged with public postings.
    restricted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    requirements: Mapped[list["JobRequirement"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )


class JobRequirement(IdMixin, Base):
    __tablename__ = "job_requirements"

    job_posting_id: Mapped[str] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(40))
    priority: Mapped[str] = mapped_column(String(20))
    raw_text: Mapped[str] = mapped_column(Text, default="")
    min_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)

    posting: Mapped[JobPosting] = relationship(back_populates="requirements")


class JobSearch(IdMixin, Base):
    __tablename__ = "job_searches"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result_count: Mapped[int] = mapped_column(Integer, default=0)


class SavedJob(IdMixin, Base):
    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", name="uq_saved_job"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_posting_id: Mapped[str] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # "saved" or "dismissed" (not interested). Null on older rows means saved.
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)


class JobMatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", name="uq_job_match"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_posting_id: Mapped[str] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    profile_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    qualification_score: Mapped[int] = mapped_column(Integer, default=0)
    career_interest_score: Mapped[int] = mapped_column(Integer, default=0)
    explanation: Mapped[str] = mapped_column(Text, default="{}")


class QualificationVerificationRequest(IdMixin, Base):
    __tablename__ = "qualification_verification_requests"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_posting_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="mandatory")
    min_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QualificationVerificationAnswer(IdMixin, Base):
    __tablename__ = "qualification_verification_answers"

    request_id: Mapped[str] = mapped_column(
        ForeignKey("qualification_verification_requests.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    choice: Mapped[str] = mapped_column(String(40))
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    setting: Mapped[str | None] = mapped_column(String(40), nullable=True)
    accomplishment: Mapped[str | None] = mapped_column(Text, nullable=True)
    proficiency: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobSearchSchedule(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_search_schedules"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text, default="{}")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackgroundTask(IdMixin, Base):
    __tablename__ = "background_jobs"

    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SearchProfile(IdMixin, TimestampMixin, Base):
    """A saved career search: role families, levels, locations, and source choices."""

    __tablename__ = "search_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    role_families: Mapped[str] = mapped_column(Text, default="[]")
    custom_titles: Mapped[str] = mapped_column(Text, default="[]")
    levels: Mapped[str] = mapped_column(Text, default="[]")
    location_scopes: Mapped[str] = mapped_column(Text, default="[]")
    city: Mapped[str] = mapped_column(String(120), default="Toronto")
    include_keywords: Mapped[str] = mapped_column(Text, default="[]")
    exclude_keywords: Mapped[str] = mapped_column(Text, default="[]")
    exclude_companies: Mapped[str] = mapped_column(Text, default="[]")
    employment_types: Mapped[str] = mapped_column(Text, default="[]")
    work_arrangements: Mapped[str] = mapped_column(Text, default="[]")
    posted_within_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=30)
    auto_refresh: Mapped[bool] = mapped_column(Boolean, default=True)
    refresh_hours: Mapped[int] = mapped_column(Integer, default=24)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
