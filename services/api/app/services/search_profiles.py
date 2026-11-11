"""Saved career search profiles.

A user can keep several (for example "Software co-op, GTA" and "Data new grad,
remote Canada"). One is the default and drives discovery and ranking.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JobPreferences, Profile, SearchProfile, User
from app.services import taxonomy
from app.services.job_sources import SearchPlan
from app.services.jsonutil import dumps, loads

POSTED_WITHIN_OPTIONS = [1, 3, 7, 14, 30, 60, 90]
EMPLOYMENT_TYPES = {
    "internship": "Internship / Co-op",
    "full_time": "Full-time",
    "part_time": "Part-time",
    "contract": "Contract",
}
WORK_ARRANGEMENTS = {"onsite": "On-site", "hybrid": "Hybrid", "remote": "Remote"}

_FAMILY_HINTS = [
    ("data_engineering", r"data engineer|etl|pipeline|data platform|warehous"),
    ("data_science", r"data scien|statistic"),
    ("data_analytics", r"data analy|analytics|business intelligence|\bbi\b"),
    ("ml_ai", r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning"),
    ("cloud_devops", r"cloud|devops|sre|infrastructure|platform"),
    ("backend", r"back[- ]?end"),
    ("full_stack", r"full[- ]?stack"),
    ("frontend", r"front[- ]?end"),
    ("software", r"software|developer|programm"),
    ("mobile", r"mobile|ios|android"),
    ("security", r"security|cyber"),
]
_LEVEL_HINTS = [
    ("intern", r"intern|co-?op|student|placement"),
    ("new_grad", r"new grad|graduate|campus"),
    ("entry", r"entry|junior|jr"),
    ("mid", r"\bmid\b|intermediate"),
]


def options() -> dict:
    return {
        "role_families": [{"value": key, "label": meta["label"]} for key, meta in taxonomy.ROLE_FAMILIES.items()],
        "levels": [{"value": key, "label": label} for key, label in taxonomy.LEVELS.items()],
        "location_scopes": [{"value": key, "label": label} for key, label in taxonomy.LOCATION_SCOPES.items()],
        "employment_types": [{"value": key, "label": label} for key, label in EMPLOYMENT_TYPES.items()],
        "work_arrangements": [{"value": key, "label": label} for key, label in WORK_ARRANGEMENTS.items()],
        "posted_within_days": POSTED_WITHIN_OPTIONS,
        "defaults": {
            "role_families": taxonomy.DEFAULT_FAMILIES,
            "levels": taxonomy.DEFAULT_LEVELS,
            "location_scopes": taxonomy.DEFAULT_SCOPES,
        },
        "cities": ["Toronto", "Mississauga", "Markham", "Vaughan", "Brampton", "Oakville", "Richmond Hill", "Waterloo", "Ottawa", "Hamilton"],
    }


def serialize(profile: SearchProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "is_default": bool(profile.is_default),
        "role_families": loads(profile.role_families, []),
        "custom_titles": loads(profile.custom_titles, []),
        "levels": loads(profile.levels, []),
        "location_scopes": loads(profile.location_scopes, []),
        "city": profile.city or "Toronto",
        "include_keywords": loads(profile.include_keywords, []),
        "exclude_keywords": loads(profile.exclude_keywords, []),
        "exclude_companies": loads(profile.exclude_companies, []),
        "employment_types": loads(profile.employment_types, []),
        "work_arrangements": loads(profile.work_arrangements, []),
        "posted_within_days": profile.posted_within_days,
        "auto_refresh": bool(profile.auto_refresh),
        "refresh_hours": profile.refresh_hours or 24,
        "last_run_at": profile.last_run_at.isoformat() if profile.last_run_at else None,
    }


def apply_payload(profile: SearchProfile, payload: dict) -> SearchProfile:
    def clean_list(key: str, allowed: set[str] | None = None) -> list[str]:
        values = [str(item).strip() for item in payload.get(key) or [] if str(item).strip()]
        if allowed is not None:
            values = [item for item in values if item in allowed]
        return list(dict.fromkeys(values))

    if "name" in payload and str(payload["name"]).strip():
        profile.name = str(payload["name"]).strip()[:120]
    if "role_families" in payload:
        profile.role_families = dumps(clean_list("role_families", set(taxonomy.ROLE_FAMILIES)))
    if "levels" in payload:
        profile.levels = dumps(clean_list("levels", set(taxonomy.LEVELS)))
    if "location_scopes" in payload:
        profile.location_scopes = dumps(clean_list("location_scopes", set(taxonomy.LOCATION_SCOPES)))
    for key in ("custom_titles", "include_keywords", "exclude_keywords", "exclude_companies"):
        if key in payload:
            setattr(profile, key, dumps(clean_list(key)))
    if "employment_types" in payload:
        profile.employment_types = dumps(clean_list("employment_types", set(EMPLOYMENT_TYPES)))
    if "work_arrangements" in payload:
        profile.work_arrangements = dumps(clean_list("work_arrangements", set(WORK_ARRANGEMENTS)))
    if "city" in payload and str(payload["city"] or "").strip():
        profile.city = str(payload["city"]).strip()[:120]
    if "posted_within_days" in payload:
        value = payload["posted_within_days"]
        profile.posted_within_days = int(value) if value not in (None, "", 0) else None
    if "auto_refresh" in payload:
        profile.auto_refresh = bool(payload["auto_refresh"])
    if "refresh_hours" in payload and payload["refresh_hours"]:
        profile.refresh_hours = max(6, int(payload["refresh_hours"]))
    return profile


def list_profiles(db: Session, user: User) -> list[SearchProfile]:
    rows = db.scalars(select(SearchProfile).where(SearchProfile.user_id == user.id).order_by(SearchProfile.created_at)).all()
    if rows:
        return list(rows)
    return [default_profile(db, user)]


def default_profile(db: Session, user: User) -> SearchProfile:
    rows = db.scalars(select(SearchProfile).where(SearchProfile.user_id == user.id).order_by(SearchProfile.created_at)).all()
    for row in rows:
        if row.is_default:
            return row
    if rows:
        rows[0].is_default = True
        db.flush()
        return rows[0]
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    created = _from_preferences(user, profile.preferences if profile else None)
    db.add(created)
    db.flush()
    return created


def get_profile_for_user(db: Session, user: User, profile_id: str | None) -> SearchProfile:
    if profile_id:
        row = db.get(SearchProfile, profile_id)
        if row is not None and row.user_id == user.id:
            return row
    return default_profile(db, user)


def set_default(db: Session, user: User, profile: SearchProfile) -> None:
    for row in db.scalars(select(SearchProfile).where(SearchProfile.user_id == user.id)).all():
        row.is_default = row.id == profile.id
    db.flush()


def _from_preferences(user: User, preferences: JobPreferences | None) -> SearchProfile:
    """Seed the first profile from onboarding preferences so earlier answers are not lost."""
    roles = loads(preferences.target_roles, []) if preferences else []
    interests = loads(preferences.career_interests, []) if preferences else []
    locations = loads(preferences.locations, []) if preferences else []
    seniority = (preferences.seniority or "") if preferences else ""
    employment = loads(preferences.employment_types, []) if preferences else []
    blob = " ".join(roles + interests).lower()
    families = [key for key, pattern in _FAMILY_HINTS if re.search(pattern, blob)]
    if not families:
        families = list(taxonomy.DEFAULT_FAMILIES)
    level_blob = f"{seniority} {' '.join(employment)} {' '.join(roles)}".lower()
    levels = [key for key, pattern in _LEVEL_HINTS if re.search(pattern, level_blob)]
    if not levels:
        levels = list(taxonomy.DEFAULT_LEVELS)
    if "unspecified" not in levels:
        levels.append("unspecified")
    if "new_grad" not in levels and ("intern" in levels or "entry" in levels):
        levels.insert(1, "new_grad")
    city = next((item for item in locations if item and "remote" not in item.lower()), "Toronto")
    if city.lower() in {"greater toronto area", "gta"}:
        city = "Toronto"
    return SearchProfile(
        user_id=user.id,
        name="My job search",
        is_default=True,
        role_families=dumps(families),
        custom_titles=dumps([role for role in roles if role][:12]),
        levels=dumps(levels),
        location_scopes=dumps(list(taxonomy.DEFAULT_SCOPES)),
        city=city,
        include_keywords="[]",
        exclude_keywords="[]",
        exclude_companies="[]",
        employment_types="[]",
        work_arrangements="[]",
        posted_within_days=30,
        auto_refresh=True,
        refresh_hours=24,
    )


def plan_from_profile(profile: SearchProfile, *, widen: bool = True, work_authorization: dict | None = None) -> SearchPlan:
    """Discovery plan. `widen` stores a slightly larger set than the default view so filters can be relaxed without a new search."""
    data = serialize(profile)
    families = data["role_families"] or list(taxonomy.DEFAULT_FAMILIES)
    levels = data["levels"] or list(taxonomy.DEFAULT_LEVELS)
    scopes = data["location_scopes"] or list(taxonomy.DEFAULT_SCOPES)
    if widen:
        if "unspecified" not in levels:
            levels = levels + ["unspecified"]
        if "canada_other" not in scopes:
            scopes = scopes + ["canada_other"]
    if work_authorization and work_authorization.get("us") == "authorized" and "remote_us" not in scopes:
        scopes = scopes + ["remote_us"]
    terms = [title for title in data["custom_titles"] if title][:4]
    return SearchPlan(
        families=families,
        levels=levels,
        scopes=scopes,
        terms=terms,
        city=data["city"],
        max_age_days=max(data["posted_within_days"] or 90, 60) if widen else data["posted_within_days"],
        exclude_keywords=data["exclude_keywords"],
    )
