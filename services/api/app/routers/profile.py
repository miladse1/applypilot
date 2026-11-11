
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Certification, Education, JobPreferences, ProfileVersion, Project, User, WorkExperience
from app.routers.common import error, not_found
from app.services.applications import invalidate_user_approvals
from app.services.jsonutil import dumps, loads
from app.services.profile_ops import get_profile, parse_date, serialize_preferences, serialize_profile, snapshot_profile, upsert_profile_skill

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


class ProfilePatch(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    location: str | None = None
    portfolio_url: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    headline: str | None = None
    summary: str | None = None


class EducationIn(BaseModel):
    institution: str
    degree: str | None = None
    program: str | None = None
    graduation_date: str | None = None
    coursework: str | None = None
    achievements: str | None = None


class ExperienceIn(BaseModel):
    employer: str
    title: str
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    responsibilities: list[str] = Field(default_factory=list)
    achievements: str = ""
    technologies: list[str] = Field(default_factory=list)


class ProjectIn(BaseModel):
    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    responsibilities: str = ""
    results: str = ""
    url: str | None = None


class CertificationIn(BaseModel):
    name: str
    issuer: str | None = None
    issue_date: str | None = None
    expiration_date: str | None = None
    credential_id: str | None = None
    status: str = "active"


class SkillIn(BaseModel):
    name: str
    proficiency: str | None = None
    confirmation_status: str = "confirmed"
    context: str | None = None
    setting: str | None = None
    duration_months: int | None = None


class PreferencesIn(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    work_arrangements: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "USD"
    willing_to_relocate: bool | None = None
    seniority: str | None = None
    career_interests: list[str] = Field(default_factory=list)


def _changed(db: Session, user: User):
    snapshot_profile(db, get_profile(db, user))
    invalidate_user_approvals(db, user, "The professional profile changed after approval.")
    db.commit()


@router.get("")
def read_profile(user: User = Depends(get_current_user)):
    return serialize_profile(user.profile)


@router.get("/skill-catalog")
def skill_catalog(user: User = Depends(get_current_user)):
    from app.services.skills import CATALOG

    return [{"key": key, "name": meta["name"], "category": meta["category"]} for key, meta in sorted(CATALOG.items(), key=lambda pair: pair[1]["name"].lower())]


class AuthorizationIn(BaseModel):
    canada: str | None = None
    us: str | None = None
    needs_sponsorship: bool | None = None


@router.get("/work-authorization")
def read_authorization(user: User = Depends(get_current_user)):
    return loads(user.settings.work_authorization, {}) if user.settings else {}


@router.put("/work-authorization")
def write_authorization(payload: AuthorizationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    value = {key: item for key, item in payload.model_dump().items() if item is not None}
    user.settings.work_authorization = dumps(value)
    db.commit()
    return value


@router.patch("")
def patch_profile(payload: ProfilePatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = get_profile(db, user)
    data = payload.model_dump(exclude_unset=True)
    if "full_name" in data and data["full_name"]:
        user.full_name = data.pop("full_name").strip()
    for key, value in data.items():
        setattr(profile, key, value)
    _changed(db, user)
    return serialize_profile(profile)


@router.post("/education", status_code=201)
def add_education(payload: EducationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = get_profile(db, user)
    item = Education(
        profile_id=profile.id,
        institution=payload.institution.strip(),
        degree=payload.degree,
        program=payload.program,
        graduation_date=parse_date(payload.graduation_date),
        coursework=payload.coursework,
        achievements=payload.achievements,
        source="user_reported",
    )
    db.add(item)
    _changed(db, user)
    return {"id": item.id}


@router.put("/education/{item_id}")
def update_education(item_id: str, payload: EducationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(Education, item_id)
    if item is None or item.profile_id != user.profile.id:
        raise not_found()
    item.institution = payload.institution.strip()
    item.degree = payload.degree
    item.program = payload.program
    item.graduation_date = parse_date(payload.graduation_date)
    item.coursework = payload.coursework
    item.achievements = payload.achievements
    _changed(db, user)
    return {"id": item.id}


@router.delete("/education/{item_id}")
def delete_education(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(Education, item_id)
    if item is None or item.profile_id != user.profile.id:
        raise not_found()
    db.delete(item)
    _changed(db, user)
    return {"ok": True}


@router.post("/experience", status_code=201)
def add_experience(payload: ExperienceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = get_profile(db, user)
    item = WorkExperience(
        profile_id=profile.id,
        employer=payload.employer.strip(),
        title=payload.title.strip(),
        location=payload.location,
        start_date=parse_date(payload.start_date),
        end_date=parse_date(payload.end_date),
        is_current=payload.is_current,
        responsibilities=dumps(payload.responsibilities),
        achievements=payload.achievements,
        technologies=dumps(payload.technologies),
        source="user_reported",
    )
    db.add(item)
    _changed(db, user)
    return {"id": item.id}


@router.put("/experience/{item_id}")
def update_experience(item_id: str, payload: ExperienceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(WorkExperience, item_id)
    if item is None or item.profile_id != user.profile.id:
        raise not_found()
    item.employer = payload.employer.strip()
    item.title = payload.title.strip()
    item.location = payload.location
    item.start_date = parse_date(payload.start_date)
    item.end_date = parse_date(payload.end_date)
    item.is_current = payload.is_current
    item.responsibilities = dumps(payload.responsibilities)
    item.achievements = payload.achievements
    item.technologies = dumps(payload.technologies)
    _changed(db, user)
    return {"id": item.id}


@router.delete("/experience/{item_id}")
def delete_experience(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(WorkExperience, item_id)
    if item is None or item.profile_id != user.profile.id:
        raise not_found()
    db.delete(item)
    _changed(db, user)
    return {"ok": True}


@router.post("/projects", status_code=201)
def add_project(payload: ProjectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = get_profile(db, user)
    item = Project(
        profile_id=profile.id,
        name=payload.name.strip(),
        description=payload.description,
        technologies=dumps(payload.technologies),
        responsibilities=payload.responsibilities,
        results=payload.results,
        url=payload.url,
        source="user_reported",
    )
    db.add(item)
    _changed(db, user)
    return {"id": item.id}


@router.put("/projects/{item_id}")
def update_project(item_id: str, payload: ProjectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(Project, item_id)
    if item is None or item.profile_id != user.profile.id:
        raise not_found()
    item.name = payload.name.strip()
    item.description = payload.description
    item.technologies = dumps(payload.technologies)
    item.responsibilities = payload.responsibilities
    item.results = payload.results
    item.url = payload.url
    _changed(db, user)
    return {"id": item.id}


@router.delete("/projects/{item_id}")
def delete_project(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(Project, item_id)
    if item is None or item.profile_id != user.profile.id:
        raise not_found()
    db.delete(item)
    _changed(db, user)
    return {"ok": True}


@router.post("/certifications", status_code=201)
def add_certification(payload: CertificationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = get_profile(db, user)
    item = Certification(
        profile_id=profile.id,
        name=payload.name.strip(),
        issuer=payload.issuer,
        issue_date=parse_date(payload.issue_date),
        expiration_date=parse_date(payload.expiration_date),
        credential_id=payload.credential_id,
        status=payload.status,
        source="user_reported",
    )
    db.add(item)
    _changed(db, user)
    return {"id": item.id}


@router.delete("/certifications/{item_id}")
def delete_certification(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(Certification, item_id)
    if item is None or item.profile_id != user.profile.id:
        raise not_found()
    db.delete(item)
    _changed(db, user)
    return {"ok": True}


@router.post("/skills", status_code=201)
def add_skill(payload: SkillIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.confirmation_status == "independently_verified":
        raise error(400, "invalid_source", "A user-reported skill cannot be marked independently verified.")
    if payload.confirmation_status == "in_progress":
        payload.proficiency = "learning"
    profile = get_profile(db, user)
    row = upsert_profile_skill(
        db,
        profile,
        payload.name,
        confirmation_status=payload.confirmation_status,
        source="user_reported",
        proficiency=payload.proficiency,
        context=payload.context,
        setting=payload.setting,
        duration_months=payload.duration_months,
        evidence=payload.context,
    )
    _changed(db, user)
    return {"id": row.id, "normalized_name": row.skill.normalized_name}


@router.delete("/skills/{item_id}")
def delete_skill(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import ProfileSkill

    item = db.get(ProfileSkill, item_id)
    if item is None or item.profile_id != user.profile.id:
        raise not_found()
    db.delete(item)
    _changed(db, user)
    return {"ok": True}


@router.get("/preferences")
def read_preferences(user: User = Depends(get_current_user)):
    return serialize_preferences(user.profile.preferences)


@router.put("/preferences")
def write_preferences(payload: PreferencesIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    preferences = user.profile.preferences or JobPreferences(profile_id=user.profile.id)
    preferences.target_roles = dumps(payload.target_roles)
    preferences.industries = dumps(payload.industries)
    preferences.locations = dumps(payload.locations)
    preferences.work_arrangements = dumps(payload.work_arrangements)
    preferences.employment_types = dumps(payload.employment_types)
    preferences.salary_min = payload.salary_min
    preferences.salary_max = payload.salary_max
    preferences.salary_currency = payload.salary_currency
    preferences.willing_to_relocate = payload.willing_to_relocate
    preferences.seniority = payload.seniority
    preferences.career_interests = dumps(payload.career_interests)
    db.add(preferences)
    _changed(db, user)
    return serialize_preferences(preferences)


@router.get("/versions")
def versions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ProfileVersion).where(ProfileVersion.profile_id == user.profile.id).order_by(ProfileVersion.version_number.desc())
    ).all()
    return [
        {"id": row.id, "version_number": row.version_number, "created_at": row.created_at.isoformat()}
        for row in rows
    ]


@router.get("/versions/{version_id}")
def version_detail(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(ProfileVersion, version_id)
    if row is None or row.profile_id != user.profile.id:
        raise not_found()
    return {"id": row.id, "version_number": row.version_number, "snapshot": loads(row.snapshot, {}), "created_at": row.created_at.isoformat()}
