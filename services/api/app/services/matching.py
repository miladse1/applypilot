"""Explainable qualification and career-interest assessments.

Undocumented qualifications stay unverified. They are not scored as missing skills.
Scores are internal assessments, not ATS scores or hiring probabilities.
"""

from __future__ import annotations

import re
from datetime import date

from app.models import JobPosting, JobPreferences, JobRequirement, Profile
from app.services.jsonutil import loads
from app.services.skills import relationship

POINT = {"matched": 1.0, "partial": 0.5, "in_progress": 0.25, "not_possessed": 0.0}


def _tokens(value: str | None) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(token) > 2}


def assess_requirement(profile: Profile, requirement: JobRequirement) -> dict:
    if requirement.category == "authorization":
        return {
            "name": requirement.name,
            "normalized_name": requirement.normalized_name,
            "category": requirement.category,
            "priority": requirement.priority,
            "status": "unverified",
            "explanation": "Work authorization is never inferred from a resume. You need to answer this yourself.",
            "eligibility": True,
        }
    if requirement.category == "enrollment":
        return _assess_enrollment(profile, requirement)
    if requirement.category == "certification":
        return _assess_certification(profile, requirement)
    if requirement.category == "education":
        return _assess_education(profile, requirement)
    if requirement.category == "experience":
        return _assess_experience(profile, requirement)
    if requirement.is_ambiguous or requirement.category == "other":
        return {
            "name": requirement.name,
            "normalized_name": requirement.normalized_name,
            "category": requirement.category,
            "priority": "unclear",
            "status": "unverified",
            "explanation": "This requirement is ambiguous, so it is not treated as a failed qualification.",
            "eligibility": False,
        }
    return _assess_skill(profile, requirement)


def _assess_skill(profile: Profile, requirement: JobRequirement) -> dict:
    rows = list(profile.profile_skills)
    exact = next((row for row in rows if row.skill.normalized_name == requirement.normalized_name), None)
    if exact is not None:
        status, explanation = _status_from_row(exact, requirement)
        return _item(requirement, status, explanation)
    for row in rows:
        if row.confirmation_status != "confirmed":
            continue
        relation = relationship(requirement.normalized_name, row.skill.normalized_name)
        if relation == "implies":
            return _item(
                requirement,
                "matched",
                f"Matched through confirmed {row.skill.display_name}, which covers this requirement.",
            )
        if relation == "related":
            return _item(
                requirement,
                "partial",
                f"Partially matched. You have confirmed {row.skill.display_name}, which is related but not the same requirement.",
            )
    return _item(
        requirement,
        "unverified",
        f"{requirement.name} is not documented in your professional profile. That does not mean you lack it.",
    )


def _status_from_row(row, requirement: JobRequirement) -> tuple[str, str]:
    status = row.confirmation_status
    if status == "not_possessed":
        return "not_possessed", "You reported that you do not currently have this qualification."
    if status == "in_progress" or row.proficiency == "learning":
        return "in_progress", "You are learning this skill. It is not treated as established professional experience."
    if status in {"unsure", "skipped", "pending_review"}:
        return "unverified", "This skill still needs a clear confirmation before it can count as a match."
    if status == "confirmed":
        if requirement.min_years:
            if row.duration_months is None:
                return (
                    "partial",
                    f"{requirement.name} is confirmed, but duration is not documented, so the {requirement.min_years}-year requirement is only partial.",
                )
            if row.duration_months < requirement.min_years * 12:
                return (
                    "partial",
                    f"Confirmed experience is shorter than the requested {requirement.min_years} years.",
                )
        origin = "your uploaded resume" if row.source == "resume_extracted" else "your confirmation"
        return "matched", f"Matched from {origin}. This is not an independently verified credential."
    return "unverified", "There is not enough information to decide."


def _assess_enrollment(profile: Profile, requirement: JobRequirement) -> dict:
    today = date.today()
    current = [
        item
        for item in profile.education
        if item.graduation_date is None or item.graduation_date >= today
    ]
    if current:
        school = current[0].institution
        return _item(requirement, "matched", f"Your profile lists current studies at {school}.")
    if profile.education:
        return _item(requirement, "unverified", "Your education entries look completed. Confirm you are still enrolled.")
    return _item(requirement, "unverified", "No education is documented yet.")


def _assess_certification(profile: Profile, requirement: JobRequirement) -> dict:
    if not profile.certifications:
        return _item(
            requirement,
            "unverified",
            "No license or certification is documented. This stays unverified until you confirm it.",
        )
    blob = " ".join(f"{item.name} {item.issuer or ''}" for item in profile.certifications).lower()
    if "license" in blob or requirement.normalized_name.replace("-", " ") in blob:
        return _item(requirement, "matched", "A documented certification appears to cover this requirement.")
    return _item(requirement, "unverified", "Your certifications do not clearly satisfy this requirement.")


def _assess_education(profile: Profile, requirement: JobRequirement) -> dict:
    if not profile.education:
        return _item(
            requirement,
            "unverified",
            "No education is documented yet. This is unverified, not an assumption that you lack a degree.",
        )
    needed = requirement.normalized_name
    rank = {"associate-degree": 1, "bachelor-s-degree": 2, "master-s-degree": 3, "doctoral-degree": 4}
    have = 0
    for item in profile.education:
        text = f"{item.degree or ''} {item.program or ''}".lower()
        if "ph" in text or "doctor" in text:
            have = max(have, 4)
        elif "master" in text or re.search(r"\bm\.?s\b", text):
            have = max(have, 3)
        elif "bachelor" in text or re.search(r"\bb\.?s\b", text):
            have = max(have, 2)
        elif "associate" in text:
            have = max(have, 1)
    required_rank = rank.get(needed, 2)
    if have >= required_rank and have > 0:
        return _item(requirement, "matched", "Your documented education meets this requirement.")
    if have > 0:
        return _item(requirement, "partial", "You have documented education, but it does not fully meet the stated degree.")
    return _item(requirement, "unverified", "A degree is listed without enough detail to compare.")


def _assess_experience(profile: Profile, requirement: JobRequirement) -> dict:
    months = _experience_months(profile)
    if months is None:
        return _item(
            requirement,
            "unverified",
            "Employment dates are incomplete, so years of experience stay unverified.",
        )
    needed = (requirement.min_years or 0) * 12
    if months >= needed:
        return _item(requirement, "matched", "Documented employment dates cover the requested duration.")
    if months > 0:
        return _item(requirement, "partial", "Documented employment is shorter than the requested duration.")
    return _item(requirement, "unverified", "No dated employment history is available.")


def _experience_months(profile: Profile) -> int | None:
    total = 0
    dated = False
    today = date.today()
    for item in profile.experiences:
        if not item.start_date:
            continue
        dated = True
        end = item.end_date or today
        months = (end.year - item.start_date.year) * 12 + (end.month - item.start_date.month)
        total += max(months, 0)
    if not dated:
        return None
    return total


def _item(requirement: JobRequirement, status: str, explanation: str) -> dict:
    return {
        "name": requirement.name,
        "normalized_name": requirement.normalized_name,
        "category": requirement.category,
        "priority": requirement.priority,
        "status": status,
        "explanation": explanation,
        "eligibility": False,
        "raw_text": requirement.raw_text,
    }


def qualification_score(items: list[dict]) -> int:
    considered = [
        item
        for item in items
        if item["priority"] == "mandatory" and item["category"] != "authorization" and item["status"] != "unverified"
    ]
    if not considered:
        return 0 if any(item["priority"] == "mandatory" and item["status"] != "unverified" for item in items) else 0
    # When every mandatory item is unverified, the score is withheld as 0 and the UI must show the unknown count.
    points = sum(POINT.get(item["status"], 0) for item in considered)
    return round(100 * points / len(considered))


def career_interest_score(profile: Profile, posting: JobPosting) -> tuple[int, list[str]]:
    preferences = profile.preferences
    notes = ["This is an interest alignment estimate, not a hiring probability."]
    if preferences is None or not _has_preferences(preferences):
        return 50, notes + ["Career preferences are incomplete, so interest is neutral."]
    roles = loads(preferences.target_roles, [])
    interests = loads(preferences.career_interests, [])
    industries = loads(preferences.industries, [])
    locations = loads(preferences.locations, [])
    arrangements = [item.lower() for item in loads(preferences.work_arrangements, [])]
    employment_types = [item.lower() for item in loads(preferences.employment_types, [])]
    title_tokens = _tokens(posting.title)
    role_tokens = set().union(*[_tokens(role) for role in roles]) if roles else set()
    overlap = len(title_tokens & role_tokens) / max(len(role_tokens), 1) if role_tokens else 0.4
    role_points = overlap * 40
    blob = f"{posting.title} {posting.industry or ''} {posting.description[:800]}".lower()
    interest_hits = [item for item in interests + industries if item and item.lower() in blob]
    interest_points = 30 if interest_hits else (10 if interests or industries else 15)
    if interest_hits:
        notes.append(f"Overlaps with your interest in {interest_hits[0]}.")
    location_points = 15
    if locations and posting.location:
        if any(location.lower() in posting.location.lower() for location in locations) or posting.work_arrangement == "remote":
            location_points = 15
        else:
            location_points = 4
            notes.append("Location differs from your saved preferences.")
    arrangement_points = 10
    if arrangements and posting.work_arrangement not in arrangements and posting.work_arrangement != "unknown":
        arrangement_points = 3
    employment_points = 10
    if employment_types and posting.employment_type not in employment_types and posting.employment_type != "unknown":
        employment_points = 3
    seniority_points = 10
    if preferences.seniority and posting.seniority and preferences.seniority != posting.seniority:
        seniority_points = 4
        notes.append(
            f"The role looks {posting.seniority}, while your preference is {preferences.seniority}. You can still pursue it."
        )
    score = round(role_points + interest_points + location_points + arrangement_points + employment_points + seniority_points)
    return max(0, min(100, score)), notes


def _has_preferences(preferences: JobPreferences) -> bool:
    return any(
        [
            loads(preferences.target_roles, []),
            loads(preferences.industries, []),
            loads(preferences.career_interests, []),
            preferences.seniority,
        ]
    )


def build_assessment(profile: Profile, posting: JobPosting) -> dict:
    items = [assess_requirement(profile, requirement) for requirement in posting.requirements]
    mandatory = [item for item in items if item["priority"] == "mandatory"]
    unknown = [item for item in mandatory if item["status"] == "unverified" and item["category"] != "authorization"]
    missing = [item for item in items if item["status"] == "not_possessed"]
    partial = [item for item in items if item["status"] == "partial"]
    matched = [item for item in items if item["status"] == "matched"]
    learning = [item for item in items if item["status"] == "in_progress"]
    conflicts = []
    for item in items:
        if item["category"] == "authorization":
            conflicts.append(
                {
                    "name": item["name"],
                    "message": "Eligibility is unknown until you answer. ApplyPilot will not guess.",
                }
            )
        if item["status"] == "not_possessed" and item["priority"] == "mandatory":
            conflicts.append(
                {
                    "name": item["name"],
                    "message": "You reported that this mandatory qualification is not met. You can still apply, with that warning.",
                }
            )
    interest, interest_notes = career_interest_score(profile, posting)
    assessed = [item for item in mandatory if item["status"] != "unverified" and item["category"] != "authorization"]
    score = qualification_score(items) if assessed else 0
    return {
        "qualification_score": score,
        "career_interest_score": interest,
        "score_basis": "Assessed only from documented or confirmed qualifications. Unverified items are excluded from the score and are not treated as missing.",
        "disclaimer": "These are explainable assessments, not official ATS scores or hiring probabilities.",
        "items": items,
        "matched": matched,
        "unverified": unknown,
        "partial": partial,
        "not_possessed": missing,
        "in_progress": learning,
        "eligibility_conflicts": conflicts,
        "interest_notes": interest_notes,
        "unknown_count": len(unknown),
    }


def needs_verification(profile: Profile, requirement: JobRequirement) -> bool:
    if requirement.category not in {"skill"} or requirement.is_ambiguous:
        return False
    if requirement.priority not in {"mandatory", "preferred"}:
        return False
    row = next((item for item in profile.profile_skills if item.skill.normalized_name == requirement.normalized_name), None)
    if row is None:
        return True
    if row.confirmation_status in {"not_possessed", "unsure", "in_progress"}:
        return False
    if row.confirmation_status == "skipped":
        return bool(requirement.min_years)
    if row.confirmation_status == "confirmed":
        if requirement.min_years and (row.duration_months is None or row.duration_months < requirement.min_years * 12):
            return True
        return False
    return True


def verification_prompt(requirement: JobRequirement, already_confirmed: bool, job_title: str | None = None) -> str:
    role = f"The {job_title} role" if job_title else "This position"
    if already_confirmed and requirement.min_years:
        return (
            f"{role} asks for {requirement.min_years}+ years of {requirement.name}. "
            "How long have you used it?"
        )
    wording = {"mandatory": "requires", "preferred": "prefers"}.get(requirement.priority, "mentions")
    return (
        f"{role} {wording} {requirement.name}. It is not on your resume or profile yet, which only means it "
        f"has not been documented. Have you used {requirement.name}?"
    )
