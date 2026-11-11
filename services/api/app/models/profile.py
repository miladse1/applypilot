from typing import TYPE_CHECKING
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:  # type hints only; importing at runtime would be circular
    from app.models.user import User


class Profile(IdMixin, TimestampMixin, Base):
    __tablename__ = "profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(240), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)

    user: Mapped["User"] = relationship(back_populates="profile")
    education: Mapped[list["Education"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    experiences: Mapped[list["WorkExperience"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    profile_skills: Mapped[list["ProfileSkill"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    certifications: Mapped[list["Certification"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    preferences: Mapped["JobPreferences | None"] = relationship(
        back_populates="profile", uselist=False, cascade="all, delete-orphan"
    )
    versions: Mapped[list["ProfileVersion"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class Education(IdMixin, TimestampMixin, Base):
    __tablename__ = "education"

    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    institution: Mapped[str] = mapped_column(String(240))
    degree: Mapped[str | None] = mapped_column(String(160), nullable=True)
    program: Mapped[str | None] = mapped_column(String(200), nullable=True)
    graduation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    coursework: Mapped[str | None] = mapped_column(Text, nullable=True)
    achievements: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="user_reported")
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    profile: Mapped[Profile] = relationship(back_populates="education")


class WorkExperience(IdMixin, TimestampMixin, Base):
    __tablename__ = "work_experiences"

    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    employer: Mapped[str] = mapped_column(String(240))
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    responsibilities: Mapped[str] = mapped_column(Text, default="")
    achievements: Mapped[str] = mapped_column(Text, default="")
    technologies: Mapped[str] = mapped_column(Text, default="[]")
    source: Mapped[str] = mapped_column(String(40), default="user_reported")
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    profile: Mapped[Profile] = relationship(back_populates="experiences")


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    technologies: Mapped[str] = mapped_column(Text, default="[]")
    responsibilities: Mapped[str] = mapped_column(Text, default="")
    results: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="user_reported")
    confidence: Mapped[str] = mapped_column(String(20), default="high")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    profile: Mapped[Profile] = relationship(back_populates="projects")


class Skill(IdMixin, Base):
    __tablename__ = "skills"

    normalized_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60), default="other")
    aliases: Mapped[str] = mapped_column(Text, default="[]")


class ProfileSkill(IdMixin, TimestampMixin, Base):
    __tablename__ = "profile_skills"
    __table_args__ = (UniqueConstraint("profile_id", "skill_id", name="uq_profile_skill"),)

    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    proficiency: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confirmation_status: Mapped[str] = mapped_column(String(40), default="pending_review")
    source: Mapped[str] = mapped_column(String(40), default="user_reported")
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    setting: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    profile: Mapped[Profile] = relationship(back_populates="profile_skills")
    skill: Mapped[Skill] = relationship()
    evidence: Mapped[list["SkillEvidence"]] = relationship(back_populates="profile_skill", cascade="all, delete-orphan")


class SkillEvidence(IdMixin, Base):
    __tablename__ = "skill_evidence"

    profile_skill_id: Mapped[str] = mapped_column(ForeignKey("profile_skills.id", ondelete="CASCADE"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    work_experience_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    profile_skill: Mapped[ProfileSkill] = relationship(back_populates="evidence")


class Certification(IdMixin, TimestampMixin, Base):
    __tablename__ = "certifications"

    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    issuer: Mapped[str | None] = mapped_column(String(240), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    credential_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active")
    source: Mapped[str] = mapped_column(String(40), default="user_reported")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    profile: Mapped[Profile] = relationship(back_populates="certifications")


class JobPreferences(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_preferences"

    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), unique=True)
    target_roles: Mapped[str] = mapped_column(Text, default="[]")
    industries: Mapped[str] = mapped_column(Text, default="[]")
    locations: Mapped[str] = mapped_column(Text, default="[]")
    work_arrangements: Mapped[str] = mapped_column(Text, default="[]")
    employment_types: Mapped[str] = mapped_column(Text, default="[]")
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(8), default="USD")
    willing_to_relocate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(40), nullable=True)
    career_interests: Mapped[str] = mapped_column(Text, default="[]")

    profile: Mapped[Profile] = relationship(back_populates="preferences")


class ProfileVersion(IdMixin, Base):
    __tablename__ = "profile_versions"

    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    profile: Mapped[Profile] = relationship(back_populates="versions")

