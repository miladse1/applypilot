from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class OriginalResume(IdMixin, TimestampMixin, Base):
    __tablename__ = "original_resumes"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(260))
    content_type: Mapped[str] = mapped_column(String(120))
    storage_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    parse_status: Mapped[str] = mapped_column(String(40), default="pending")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    extracted_json: Mapped[str] = mapped_column(Text, default="{}")
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Layout-aware structure of the original document and its typography.
    document_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_primary: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ResumeVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "resume_versions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_posting_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    profile_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    original_resume_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), default="tailored")
    template: Mapped[str] = mapped_column(String(40), default="classic")
    length: Mapped[str] = mapped_column(String(20), default="standard")
    title: Mapped[str] = mapped_column(String(240), default="Resume")
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    content_text: Mapped[str] = mapped_column(Text, default="")
    approved_by_user: Mapped[bool] = mapped_column(Boolean, default=False)


class CoverLetter(IdMixin, TimestampMixin, Base):
    __tablename__ = "cover_letters"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_posting_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    profile_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tone: Mapped[str] = mapped_column(String(40), default="professional")
    body: Mapped[str] = mapped_column(Text, default="")
    approved_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
