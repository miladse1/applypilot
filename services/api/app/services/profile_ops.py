"""Master Professional Profile persistence.

A resume approval copies reviewed facts into the profile. Later skill answers
update the same profile and never create a second row for an alias of a skill.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Certification,
    Education,
    JobPreferences,
    Profile,
    ProfileSkill,
    ProfileVersion,
    Project,
    Skill,
    SkillEvidence,
    User,
    WorkExperience,
)
from app.services.jsonutil import dumps, loads
from app.services.skills import normalize_skill

CONFIRMED = "confirmed"
IN_PROGRESS = "in_progress"
NOT_POSSESSED = "not_possessed"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def snapshot_profile(db: Session, profile: Profile) -> ProfileVersion:
    profile.current_version += 1
    payload = serialize_profile(profile)
    version = ProfileVersion(
        profile_id=profile.id,
        version_number=profile.current_version,
        snapshot=dumps(payload),
        created_at=datetime.now(timezone.utc),
    )
    db.add(version)
    db.flush()
    return version


def serialize_profile(profile: Profile) -> dict:
    preferences = profile.preferences
    return {
        "id": profile.id,
        "full_name": profile.user.full_name if profile.user else None,
        "phone": profile.phone,
        "location": profile.location,
        "portfolio_url": profile.portfolio_url,
        "linkedin_url": profile.linkedin_url,
        "github_url": profile.github_url,
        "headline": profile.headline,
        "summary": profile.summary,
        "version": profile.current_version,
        "education": [
            {
                "id": item.id,
                "institution": item.institution,
                "degree": item.degree,
                "program": item.program,
                "graduation_date": item.graduation_date.isoformat() if item.graduation_date else None,
                "coursework": item.coursework,
                "achievements": item.achievements,
                "source": item.source,
                "confidence": item.confidence,
                "needs_review": item.needs_review,
            }
            for item in profile.education
        ],
        "experience": [
            {
                "id": item.id,
                "employer": item.employer,
                "title": item.title,
                "location": item.location,
                "start_date": item.start_date.isoformat() if item.start_date else None,
                "end_date": item.end_date.isoformat() if item.end_date else None,
                "is_current": item.is_current,
                "responsibilities": loads(item.responsibilities, []),
                "achievements": item.achievements,
                "technologies": loads(item.technologies, []),
                "source": item.source,
                "confidence": item.confidence,
                "needs_review": item.needs_review,
            }
            for item in profile.experiences
        ],
        "projects": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "technologies": loads(item.technologies, []),
                "responsibilities": item.responsibilities,
                "results": item.results,
                "url": item.url,
                "source": item.source,
                "needs_review": item.needs_review,
            }
            for item in profile.projects
        ],
        "skills": [
            {
                "id": item.id,
                "skill_id": item.skill_id,
                "name": item.skill.display_name,
                "normalized_name": item.skill.normalized_name,
                "category": item.skill.category,
                "proficiency": item.proficiency,
                "confirmation_status": item.confirmation_status,
                "source": item.source,
                "context": item.context,
                "setting": item.setting,
                "duration_months": item.duration_months,
                "needs_review": item.needs_review,
                "evidence": [
                    {"id": evidence.id, "type": evidence.evidence_type, "description": evidence.description}
                    for evidence in item.evidence
                ],
            }
            for item in profile.profile_skills
        ],
        "certifications": [
            {
                "id": item.id,
                "name": item.name,
                "issuer": item.issuer,
                "issue_date": item.issue_date.isoformat() if item.issue_date else None,
                "expiration_date": item.expiration_date.isoformat() if item.expiration_date else None,
                "status": item.status,
                "source": item.source,
                "needs_review": item.needs_review,
            }
            for item in profile.certifications
        ],
        "preferences": serialize_preferences(preferences) if preferences else None,
    }


def serialize_preferences(preferences: JobPreferences) -> dict:
    return {
        "target_roles": loads(preferences.target_roles, []),
        "industries": loads(preferences.industries, []),
        "locations": loads(preferences.locations, []),
        "work_arrangements": loads(preferences.work_arrangements, []),
        "employment_types": loads(preferences.employment_types, []),
        "salary_min": preferences.salary_min,
        "salary_max": preferences.salary_max,
        "salary_currency": preferences.salary_currency,
        "willing_to_relocate": preferences.willing_to_relocate,
        "seniority": preferences.seniority,
        "career_interests": loads(preferences.career_interests, []),
    }


def get_profile(db: Session, user: User) -> Profile:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        raise RuntimeError("Profile missing for user.")
    return profile


def get_or_create_skill(db: Session, raw_name: str) -> Skill:
    key, display, category = normalize_skill(raw_name)
    skill = db.scalar(select(Skill).where(Skill.normalized_name == key))
    if skill:
        return skill
    skill = Skill(normalized_name=key, display_name=display, category=category, aliases="[]")
    db.add(skill)
    db.flush()
    return skill


def upsert_profile_skill(
    db: Session,
    profile: Profile,
    raw_name: str,
    *,
    confirmation_status: str,
    source: str,
    proficiency: str | None = None,
    context: str | None = None,
    setting: str | None = None,
    duration_months: int | None = None,
    needs_review: bool = False,
    evidence: str | None = None,
    evidence_type: str = "user_statement",
) -> ProfileSkill:
    skill = get_or_create_skill(db, raw_name)
    existing = db.scalar(
        select(ProfileSkill).where(ProfileSkill.profile_id == profile.id, ProfileSkill.skill_id == skill.id)
    )
    if existing is None:
        existing = ProfileSkill(
            profile_id=profile.id,
            skill_id=skill.id,
            confirmation_status=confirmation_status,
            source=source,
        )
        db.add(existing)
    existing.confirmation_status = confirmation_status
    existing.source = source
    existing.needs_review = needs_review
    if proficiency is not None:
        existing.proficiency = proficiency
    if context is not None:
        existing.context = context
    if setting is not None:
        existing.setting = setting
    if duration_months is not None:
        existing.duration_months = duration_months
    db.flush()
    if evidence:
        db.add(
            SkillEvidence(
                profile_skill_id=existing.id,
                evidence_type=evidence_type,
                description=evidence,
                created_at=datetime.now(timezone.utc),
            )
        )
    return existing


def _squash(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _text_contains(raw_text: str, value: str | None) -> bool:
    """Whether the value appears in the document, ignoring line wraps, hyphenation, and punctuation."""
    if not value:
        return False
    if value.casefold() in raw_text.casefold():
        return True
    needle = _squash(re.sub(r"\*\*", "", value))
    return bool(needle) and needle in _squash(raw_text)


def _old_parse_artifact(row: ProfileSkill) -> bool:
    """Skills an earlier parser saved by mistake: a label fused to a value ("Languages: Python"), never confirmed by the user."""
    name = row.skill.display_name
    auto_only = all(item.description == "Added by the user during review." for item in row.evidence) and not row.context
    return auto_only and (":" in name or len(name.split()) > 5)


def approve_extraction(db: Session, user: User, extraction: dict, raw_text: str) -> Profile:
    """Save user-reviewed extraction into the master profile.

    Low-confidence items are stored only when the client explicitly accepts them.
    Facts that do not appear in the source document are stored as user-reported,
    never as resume-extracted.
    """
    profile = get_profile(db, user)
    for collection in (profile.experiences, profile.education, profile.projects, profile.certifications):
        for item in list(collection):
            if item.source == "resume_extracted":
                db.delete(item)
    # Skills read from an earlier upload are replaced by this one. Skills the user confirmed stay.
    incoming = {
        normalize_skill(item.get("name") or "")[0]
        for item in extraction.get("skills") or []
        if not (item.get("needs_review") and not item.get("accepted"))
    }
    for row in list(profile.profile_skills):
        if row.source == "resume_extracted" and row.skill.normalized_name not in incoming:
            db.delete(row)
        elif row.source == "user_reported" and row.skill.normalized_name not in incoming and _old_parse_artifact(row):
            db.delete(row)
    db.flush()
    db.expire(profile, ["profile_skills"])
    contact = extraction.get("contact") or {}
    if contact.get("full_name"):
        user.full_name = contact["full_name"].strip()
    for field in ("phone", "location", "portfolio_url", "linkedin_url", "github_url"):
        if contact.get(field):
            setattr(profile, field, contact[field])
    if extraction.get("summary"):
        profile.summary = extraction["summary"]

    for item in extraction.get("skills") or []:
        if item.get("needs_review") and not item.get("accepted"):
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        in_document = _text_contains(raw_text, name) or _text_contains(raw_text, item.get("normalized_name"))
        source = "resume_extracted" if in_document else "user_reported"
        upsert_profile_skill(
            db,
            profile,
            name,
            confirmation_status=CONFIRMED,
            source=source,
            needs_review=False,
            evidence="Listed on the uploaded resume." if in_document else "Added by the user during review.",
            evidence_type="resume" if in_document else "user_statement",
        )

    for item in extraction.get("experience") or []:
        if item.get("rejected"):
            continue
        employer = (item.get("employer") or "").strip()
        title = (item.get("title") or "").strip()
        if not employer or not title:
            continue
        in_document = _text_contains(raw_text, employer) and _text_contains(raw_text, title)
        responsibilities = item.get("responsibilities") or []
        if isinstance(responsibilities, str):
            responsibilities = [responsibilities]
        kept = [bullet for bullet in responsibilities if _text_contains(raw_text, bullet) or item.get("accepted")]
        db.add(
            WorkExperience(
                profile_id=profile.id,
                employer=employer,
                title=title,
                location=item.get("location"),
                start_date=parse_date(item.get("start_date")),
                end_date=parse_date(item.get("end_date")),
                is_current=bool(item.get("is_current")),
                responsibilities=dumps(kept),
                achievements=item.get("achievements") or "",
                technologies=dumps(item.get("technologies") or []),
                source="resume_extracted" if in_document else "user_reported",
                confidence="medium" if in_document else "low",
                needs_review=not in_document,
            )
        )

    for item in extraction.get("education") or []:
        if item.get("rejected"):
            continue
        institution = (item.get("institution") or "").strip()
        if not institution:
            continue
        in_document = _text_contains(raw_text, institution)
        db.add(
            Education(
                profile_id=profile.id,
                institution=institution,
                degree=item.get("degree"),
                program=item.get("program"),
                graduation_date=parse_date(item.get("graduation_date")),
                coursework=item.get("coursework"),
                achievements="\n".join(part for part in [item.get("achievements") or "", f"GPA: {item['gpa']}" if item.get("gpa") else ""] if part) or None,
                source="resume_extracted" if in_document else "user_reported",
                confidence="medium" if in_document else "low",
                needs_review=not in_document or bool(item.get("needs_review")),
            )
        )

    for item in extraction.get("projects") or []:
        if item.get("needs_review") and not item.get("accepted"):
            continue
        name = (item.get("name") or "").strip()
        if not name or name.lower() == "none listed":
            continue
        in_document = _text_contains(raw_text, name)
        bullets = item.get("bullets") or [line for line in (item.get("responsibilities") or "").split("\n") if line.strip()]
        db.add(
            Project(
                profile_id=profile.id,
                name=name,
                description=item.get("description") or " ".join(bullets),
                technologies=dumps(item.get("technologies") or []),
                responsibilities="\n".join(bullets),
                results=item.get("results") or "",
                url=item.get("url"),
                source="resume_extracted" if in_document else "user_reported",
                needs_review=not in_document,
            )
        )

    for item in extraction.get("certifications") or []:
        if item.get("rejected"):
            continue
        name = (item.get("name") or "").strip()
        if not name or name.lower().startswith("none"):
            continue
        in_document = _text_contains(raw_text, name)
        db.add(
            Certification(
                profile_id=profile.id,
                name=name,
                issuer=item.get("issuer"),
                issue_date=parse_date(item.get("issue_date")),
                expiration_date=parse_date(item.get("expiration_date")),
                status=item.get("status") or "active",
                source="resume_extracted" if in_document else "user_reported",
                needs_review=not in_document,
            )
        )

    db.flush()
    db.expire(profile, ["experiences", "education", "projects", "certifications", "profile_skills"])
    snapshot_profile(db, profile)
    return profile


def export_user(db: Session, user: User) -> dict:
    profile = get_profile(db, user)
    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name},
        "profile": serialize_profile(profile),
    }


def dump_json(value: dict) -> str:
    return json.dumps(value)
