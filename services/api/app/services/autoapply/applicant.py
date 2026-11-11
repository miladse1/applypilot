"""Everything ApplyPilot may put into an application form, and nothing else.

Values come from the profile, answers the user saved, and the approved application
packet (tailored resume, cover letter, answers). Files are rendered from the exact
approved versions.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Application, CoverLetter, JobPosting, ResumeVersion, SavedAnswer, User
from app.services.privacy import ai_allowed
from app.services.jsonutil import loads

PROVINCES = {
    "ON": "Ontario", "QC": "Quebec", "BC": "British Columbia", "AB": "Alberta", "MB": "Manitoba", "SK": "Saskatchewan",
    "NS": "Nova Scotia", "NB": "New Brunswick", "NL": "Newfoundland and Labrador", "PE": "Prince Edward Island",
    "YT": "Yukon", "NT": "Northwest Territories", "NU": "Nunavut",
}


@dataclass
class Applicant:
    values: dict[str, str]
    saved: dict[str, str]
    answers: list[dict]
    company: str
    employers: set[str]
    resume_path: Path
    cover_letter_path: Path | None = None
    cover_letter_text: str | None = None
    job_country: str | None = None
    run_answers: dict[str, str] = field(default_factory=dict)
    # The exact tailored resume being uploaded, so the run can show and verify it.
    resume_version_id: str | None = None
    resume_title: str = ""
    resume_sha256: str = ""  # of the PDF file attached to the form
    resume_content_sha256: str = ""  # of the approved version's content, to notice edits
    resume_text: str = ""
    skills: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    job_title: str = ""
    job_description: str = ""
    job_source: str = ""

    def facts_for_ai(self) -> dict[str, str]:
        """Verified facts a model may map a question onto. Free-text answers are excluded."""
        facts = {key: value for key, value in self.values.items() if value}
        for key in ("work_authorization", "sponsorship", "relocation", "start_date", "age_18", "how_heard", "country", "location"):
            if self.saved.get(key):
                facts[key] = self.saved[key]
        facts["previously_worked_for_this_company"] = "Yes" if self.previously_employed() else "No"
        return facts

    def previously_employed(self) -> bool:
        company = _company_key(self.company)
        return bool(company) and any(company in employer or employer in company for employer in self.employers if employer)


def _company_key(name: str) -> str:
    name = re.sub(r"\b(inc|ltd|llc|corp|corporation|co|limited|group|canada|technologies)\b\.?", "", (name or "").lower())
    return re.sub(r"[^a-z0-9]", "", name)


def application_dir(application_id: str) -> Path:
    path = get_settings().storage_path / "applications" / application_id
    path.mkdir(parents=True, exist_ok=True)
    return path


class WrongResume(Exception):
    """The application points at a resume that is not the approved, tailored one for this job."""


def approved_resume(db: Session, application: Application) -> ResumeVersion:
    version = db.get(ResumeVersion, application.resume_version_id) if application.resume_version_id else None
    if version is None or version.user_id != application.user_id:
        raise WrongResume("This application has no resume. Prepare it again.")
    if version.job_posting_id and version.job_posting_id != application.job_posting_id:
        raise WrongResume("This application's resume was tailored for a different job. Regenerate it for this job and approve again.")
    if version.kind != "tailored":
        raise WrongResume("This application does not have a resume tailored for this job yet. Tailor it and approve again.")
    return version


def _render_resume(db: Session, user: User, application: Application, folder: Path) -> Path:
    """Render the approved tailored version as it is now, including the user's edits from review."""
    from app.services.documents import render_pdf
    from app.services.resume_render import render_document_pdf

    version = approved_resume(db, application)
    content = loads(version.content_json, {})
    profile = user.profile
    name = re.sub(r"[^A-Za-z0-9]+", "_", user.full_name or "Resume").strip("_")
    # One folder per approved content, so the file attached to a form is never overwritten.
    fingerprint = hashlib.sha256(f"{version.id}|{version.content_json}".encode()).hexdigest()[:16]
    target = folder / f"resume-{fingerprint}"
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{name}_Resume.pdf"
    if path.exists():
        return path
    if content.get("format") == "document":
        contact = content.get("contact_overrides") or {"linkedin_url": profile.linkedin_url, "github_url": profile.github_url, "portfolio_url": profile.portfolio_url}
        data, _fit = render_document_pdf(content["document"], content.get("style"), contact_overrides=contact, title=version.title)
    else:
        data = render_pdf(content)
    path.write_bytes(data)
    return path


def _render_letter(user: User, body: str, folder: Path) -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    name = re.sub(r"[^A-Za-z0-9]+", "_", user.full_name or "Cover").strip("_")
    target = folder / f"letter-{hashlib.sha256(body.encode()).hexdigest()[:16]}"
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{name}_Cover_Letter.pdf"
    if path.exists():
        return path
    styles = getSampleStyleSheet()
    story = []
    for paragraph in [part.strip() for part in body.split("\n\n") if part.strip()]:
        story += [Paragraph(paragraph.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>"), styles["BodyText"]), Spacer(1, 8)]
    SimpleDocTemplate(str(path), pagesize=letter, leftMargin=72, rightMargin=72, topMargin=72, bottomMargin=72).build(story)
    return path


def build_applicant(db: Session, user: User, application: Application, run_answers: dict[str, str] | None = None) -> Applicant:
    profile = user.profile
    posting = db.get(JobPosting, application.job_posting_id)
    folder = application_dir(application.id)
    full_name = (user.full_name or "").strip()
    parts = full_name.split()
    saved = {row.question_key: row.answer for row in db.scalars(select(SavedAnswer).where(SavedAnswer.user_id == user.id)).all()}
    location = profile.location or saved.get("location") or ""
    city, province, country = "", "", ""
    if location:
        pieces = [piece.strip() for piece in location.split(",") if piece.strip()]
        city = pieces[0] if pieces else ""
        if len(pieces) > 1:
            province = PROVINCES.get(pieces[1].upper(), pieces[1])
            if pieces[1].upper() in PROVINCES or pieces[1] in PROVINCES.values():
                country = "Canada"
        if len(pieces) > 2:
            country = pieces[2]
    country = saved.get("country") or country
    if not country:
        # The country of your current job is a safe stand-in; city and address are always asked.
        current_job = next((item for item in profile.experiences if item.is_current), None)
        place = (current_job.location if current_job and current_job.location else "") or ""
        tail = place.split(",")[-1].strip() if place else ""
        if tail.upper() in PROVINCES or tail in PROVINCES.values():
            country = "Canada"
    education = profile.education[0] if profile.education else None
    values = {
        "first_name": parts[0] if parts else "",
        "last_name": parts[-1] if len(parts) > 1 else "",
        "full_name": full_name,
        "preferred_name": parts[0] if parts else "",
        "email": user.email,
        "phone": profile.phone or "",
        "location": location,
        "city": saved.get("city") or city,
        "province": saved.get("province") or province,
        "country": country,
        "postal_code": saved.get("postal_code", ""),
        "address_line1": saved.get("address_line1", ""),
        "linkedin": profile.linkedin_url or saved.get("linkedin", ""),
        "github": profile.github_url or saved.get("github", ""),
        "website": profile.portfolio_url or profile.github_url or saved.get("website", ""),
        "school": education.institution if education else "",
        "degree": education.degree if education and education.degree else "",
        "discipline": education.program if education and education.program else "",
        "graduation": education.graduation_date.strftime("%B %Y") if education and education.graduation_date else saved.get("graduation", ""),
        "phone_extension": "",
        "current_company": "",
        "current_title": "",
    }
    current = next((item for item in profile.experiences if item.is_current), None)
    if current:
        values["current_company"], values["current_title"] = current.employer, current.title
    answers = [item for item in loads(application.answers_json, []) if (item.get("answer") or "").strip()]
    letter = db.get(CoverLetter, application.cover_letter_id) if application.cover_letter_id else None
    version = approved_resume(db, application)
    resume_path = _render_resume(db, user, application, folder)
    from app.services.tailoring import confirmed_skills

    return Applicant(
        values=values,
        saved=saved,
        answers=answers,
        company=posting.company if posting else "",
        employers={_company_key(item.employer) for item in profile.experiences},
        resume_path=resume_path,
        cover_letter_path=_render_letter(user, letter.body, folder) if letter and letter.body else None,
        cover_letter_text=letter.body if letter else None,
        job_country=_job_country(posting.location if posting else ""),
        run_answers=dict(run_answers or {}),
        resume_version_id=version.id,
        resume_title=version.title,
        resume_sha256=hashlib.sha256(resume_path.read_bytes()).hexdigest(),
        resume_content_sha256=hashlib.sha256(f"{version.id}|{version.content_json}".encode()).hexdigest(),
        resume_text=version.content_text or "",
        skills=sorted(meta["name"] for meta in confirmed_skills(profile).values()),
        projects=[f"{item.name}: {(item.responsibilities or item.description or '')[:600]}" for item in profile.projects],
        job_title=posting.title if posting else "",
        # A restricted (Experience York) posting's text is never given to Claude's answer drafting.
        job_description=(posting.description or "")[:6000] if posting and ai_allowed(db, user.id, posting) else "",
        job_source=(posting.source_label or posting.source or "") if posting else "",
    )


def _job_country(location: str | None) -> str | None:
    text = (location or "").lower()
    if re.search(r"canada|\b(on|qc|bc|ab|mb|sk|ns|nb)\b|toronto|ontario|vancouver|montreal", text):
        return "canada"
    if re.search(r"united states|\busa?\b|, [a-z]{2}$", text):
        return "us"
    return None
