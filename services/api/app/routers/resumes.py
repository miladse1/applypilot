import hashlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Application, JobPosting, OriginalResume, ResumeVersion, User
from app.routers.common import error, not_found
from app.services.applications import invalidate_approval
from app.services.documents import (
    TruthfulnessError,
    compare_resumes,
    render_docx,
    render_pdf,
    resume_to_text,
    store_version,
    validate_resume_content,
)
from app.services.documents_io import DocumentError, extract_text, validate_upload
from app.services.jsonutil import dumps, loads
from app.services.profile_ops import approve_extraction, get_profile, serialize_profile
from app.services.resume_import import create_tailored_version, extract_resume, primary_resume
from app.services.resume_parser import parse_resume_text
from app.services.resume_render import edit_original_docx, render_document_docx, render_document_pdf
from app.services.tailoring import apply_user_edits, document_text, structural_problems

router = APIRouter(prefix="/api/v1", tags=["resumes"])


class ExtractionPatch(BaseModel):
    extraction: dict


class TailorIn(BaseModel):
    job_id: str
    template: str = "original"
    length: str = "standard"
    use_ai: bool = True


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ResumeEdit(BaseModel):
    content: dict | None = None
    text: dict[str, str] = Field(default_factory=dict)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    hidden: dict[str, bool] = Field(default_factory=dict)
    revert: list[str] = Field(default_factory=list)


def _build_sample_docx(text: str) -> bytes:
    from docx import Document

    document = Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _owned_resume(db: Session, user: User, resume_id: str) -> OriginalResume:
    resume = db.get(OriginalResume, resume_id)
    if resume is None or resume.user_id != user.id:
        raise not_found()
    return resume


@router.post("/resumes", status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    replace: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a resume. With `replace=<resume id>`, the new file becomes the main resume and the old one is removed."""
    data = await file.read()
    try:
        extension = validate_upload(file.filename or "resume", file.content_type or "", data, get_settings().max_upload_bytes)
    except DocumentError as exc:
        raise error(400, "invalid_file", str(exc)) from exc
    digest = hashlib.sha256(data).hexdigest()
    folder = Path(get_settings().storage_path) / user.id
    folder.mkdir(parents=True, exist_ok=True)
    resume = OriginalResume(
        user_id=user.id,
        filename=Path(file.filename or "resume").name,
        content_type=file.content_type or "application/octet-stream",
        storage_path="",
        size_bytes=len(data),
        sha256=digest,
        parse_status="pending",
    )
    db.add(resume)
    db.flush()
    path = folder / f"{resume.id}{extension}"
    path.write_bytes(data)
    resume.storage_path = str(path)
    try:
        text = extract_text(path, resume.content_type)
    except DocumentError as exc:
        resume.parse_status = "failed"
        resume.review_notes = str(exc)
        db.commit()
        raise error(400, "unreadable_file", str(exc)) from exc
    if not text.strip():
        resume.parse_status = "failed"
        resume.review_notes = "No text could be extracted. Scanned documents are not supported yet. Export your resume as a text-based PDF or DOCX."
        db.commit()
        raise error(400, "empty_text", resume.review_notes)
    resume.raw_text = text
    extract_resume(resume, path)
    resume.parse_status = "parsed"
    previous = _owned_resume(db, user, replace) if replace else None
    if previous is not None or primary_resume(db, user) in {None, resume}:
        for row in db.scalars(select(OriginalResume).where(OriginalResume.user_id == user.id)).all():
            row.is_primary = row.id == resume.id
    if previous is not None and previous.id != resume.id:
        _remove_resume(db, previous)
    db.commit()
    return _resume_out(resume, primary_id=resume.id if previous is not None else None)


@router.post("/resumes/sample", status_code=201)
def upload_sample(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not get_settings().demo_mode:
        raise error(404, "not_found", "Sample resumes are available only in demo mode.")
    sample_path = Path(__file__).resolve().parents[1] / "data" / "sample_resume.txt"
    text = sample_path.read_text()
    data = _build_sample_docx(text)
    folder = Path(get_settings().storage_path) / user.id
    folder.mkdir(parents=True, exist_ok=True)
    parsed = parse_resume_text(text)
    resume = OriginalResume(
        user_id=user.id,
        filename="sample-resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_path="",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        parse_status="parsed",
        raw_text=text,
        document_json=dumps(parsed.pop("document")),
        style_json=dumps(parsed.pop("style")),
        parser=parsed.get("parser"),
        extracted_json=dumps(parsed),
    )
    db.add(resume)
    db.flush()
    path = folder / f"{resume.id}.docx"
    path.write_bytes(data)
    resume.storage_path = str(path)
    db.commit()
    return _resume_out(resume)


@router.get("/resumes")
def list_resumes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(OriginalResume).where(OriginalResume.user_id == user.id).order_by(OriginalResume.created_at.desc())).all()
    primary = primary_resume(db, user)
    return [_resume_out(row, primary_id=primary.id if primary else None) for row in rows]


@router.get("/resumes/{resume_id}")
def get_resume(resume_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    resume = _owned_resume(db, user, resume_id)
    primary = primary_resume(db, user)
    return _resume_out(resume, include_document=True, primary_id=primary.id if primary else None)


@router.get("/resumes/{resume_id}/file")
def original_file(resume_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The original upload, unchanged."""
    resume = _owned_resume(db, user, resume_id)
    path = Path(resume.storage_path)
    if not path.exists():
        raise error(404, "file_missing", "The original file is no longer in storage.")
    media = "application/pdf" if path.suffix.lower() == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    disposition = "inline" if path.suffix.lower() == ".pdf" else "attachment"
    return Response(content=path.read_bytes(), media_type=media, headers={"Content-Disposition": f'{disposition}; filename="{resume.filename}"'})


@router.get("/resumes/{resume_id}/preview")
def original_preview(resume_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A PDF view of the original. PDFs are returned as uploaded; DOCX is shown through the layout reconstruction."""
    resume = _owned_resume(db, user, resume_id)
    path = Path(resume.storage_path)
    if path.suffix.lower() == ".pdf" and path.exists():
        return Response(content=path.read_bytes(), media_type="application/pdf", headers={"Content-Disposition": "inline"})
    if not resume.document_json:
        extract_resume(resume, path)
        db.commit()
    profile = get_profile(db, user)
    data, _fit = render_document_pdf(loads(resume.document_json, {}), loads(resume.style_json, None), contact_overrides=_contact(profile))
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": "inline"})


@router.post("/resumes/{resume_id}/reparse")
def reparse_resume(resume_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Read the stored original again with the current parser. The profile changes only after you save the review."""
    resume = _owned_resume(db, user, resume_id)
    path = Path(resume.storage_path)
    if not path.exists():
        raise error(404, "file_missing", "The original file is no longer in storage.")
    if not resume.raw_text:
        resume.raw_text = extract_text(path, resume.content_type)
    extract_resume(resume, path)
    resume.parse_status = "parsed"
    resume.approved_at = None
    db.commit()
    return _resume_out(resume, include_document=True)


@router.post("/resumes/{resume_id}/primary")
def make_primary(resume_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    resume = _owned_resume(db, user, resume_id)
    for row in db.scalars(select(OriginalResume).where(OriginalResume.user_id == user.id)).all():
        row.is_primary = row.id == resume.id
    db.commit()
    return _resume_out(resume, primary_id=resume.id)


@router.delete("/resumes/{resume_id}")
def delete_resume(resume_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete an uploaded file. Your profile and tailored versions made from it are kept."""
    resume = _owned_resume(db, user, resume_id)
    was_primary = primary_resume(db, user) is resume
    _remove_resume(db, resume)
    db.flush()
    if was_primary:
        remaining = primary_resume(db, user)
        if remaining is not None:
            remaining.is_primary = True
    db.commit()
    return {"ok": True}


def _remove_resume(db: Session, resume: OriginalResume) -> None:
    path = Path(resume.storage_path) if resume.storage_path else None
    db.delete(resume)
    if path is not None and path.exists():
        path.unlink()


@router.patch("/resumes/{resume_id}/extraction")
def edit_extraction(resume_id: str, payload: ExtractionPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    resume = _owned_resume(db, user, resume_id)
    extraction = dict(payload.extraction)
    extraction.pop("document", None)
    extraction.pop("style", None)
    resume.extracted_json = dumps(extraction)
    resume.parse_status = "reviewed"
    db.commit()
    return _resume_out(resume)


@router.post("/resumes/{resume_id}/approve")
def approve_resume(resume_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    resume = _owned_resume(db, user, resume_id)
    if resume.parse_status == "failed":
        raise error(400, "not_parsed", "This file could not be parsed.")
    extraction = loads(resume.extracted_json, {})
    approve_extraction(db, user, extraction, resume.raw_text)
    resume.parse_status = "approved"
    resume.approved_at = datetime.now(timezone.utc)
    if not resume.document_json and Path(resume.storage_path).exists():
        extract_resume(resume, Path(resume.storage_path), keep_extraction=True)
    for row in db.scalars(select(OriginalResume).where(OriginalResume.user_id == user.id)).all():
        row.is_primary = row.id == resume.id
    profile = get_profile(db, user)
    content = {
        "format": "document",
        "origin": "original",
        "source_resume_id": resume.id,
        "document": loads(resume.document_json, {}),
        "original_document": loads(resume.document_json, {}),
        "style": loads(resume.style_json, None),
        "changes": [],
        "generation": {"method": "original", "provider": None, "note": "Your resume as uploaded."},
        "contact_overrides": _contact(profile),
    }
    store_version(db, user_id=user.id, job_posting_id=None, profile_version_id=None, kind="base", template="original", length="full", title="Original resume", content=content)
    db.commit()
    return {"resume": _resume_out(resume), "profile": serialize_profile(profile)}


@router.post("/resume-versions/tailor", status_code=201)
def tailor(payload: TailorIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.job_sync import posting_visible

    posting = db.get(JobPosting, payload.job_id)
    if posting is None or not posting_visible(posting, user, get_settings()):
        raise not_found()
    version = create_tailored_version(db, user, posting, use_ai=payload.use_ai)
    db.commit()
    return _version_out(version, include_content=True)


@router.get("/resume-versions")
def list_versions(job_id: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(ResumeVersion).where(ResumeVersion.user_id == user.id)
    if job_id:
        stmt = stmt.where(ResumeVersion.job_posting_id == job_id)
    rows = db.scalars(stmt.order_by(ResumeVersion.created_at.desc())).all()
    return [_version_out(row) for row in rows]


@router.get("/resume-versions/{version_id}")
def get_version(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _version_out(_owned_version(db, user, version_id), include_content=True)


@router.patch("/resume-versions/{version_id}")
def edit_version(version_id: str, payload: ResumeEdit, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    version = _owned_version(db, user, version_id)
    content = loads(version.content_json, {})
    profile = get_profile(db, user)
    warnings: list[str] = []
    if content.get("format") == "document" and payload.content is None:
        content, warnings = apply_user_edits(content, payload.model_dump(), profile)
        version.content_text = document_text(content["document"])
    elif content.get("format") == "document":
        new_document = (payload.content or {}).get("document") or {}
        problems = structural_problems(new_document, content.get("original_document") or {}, content.get("added_entries"))
        if problems:
            raise error(422, "untruthful_resume", " ".join(dict.fromkeys(problems)))
        content["document"] = new_document
        version.content_text = document_text(new_document)
    else:
        new_content = payload.content or {}
        problems = validate_resume_content(new_content, profile)
        if problems:
            raise error(422, "untruthful_resume", " ".join(problems))
        content = new_content
        version.content_text = resume_to_text(content)
    version.content_json = dumps(content)
    _resume_edited(db, user, version)
    db.commit()
    return {**_version_out(version, include_content=True), "warnings": warnings}


def _resume_edited(db: Session, user: User, version: ResumeVersion) -> None:
    version.approved_by_user = False
    for application in _applications_using(db, user.id, version.id):
        invalidate_approval(db, application, "The resume was edited after approval.")


@router.post("/resume-versions/{version_id}/chat")
def chat_about_resume(version_id: str, payload: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ask Claude about this tailored resume, or ask it to change something. Changes are checked and applied."""
    from app.services import resume_chat
    from app.services.ai import AIError, ai_scope, get_provider

    version = _owned_version(db, user, version_id)
    content = loads(version.content_json, {})
    if content.get("format") != "document":
        raise error(400, "old_format", "This version uses the older format. Regenerate it to chat about it.")
    provider = get_provider(get_settings())
    if provider is None:
        raise error(400, "ai_unavailable", "Add an Anthropic API key to chat with Claude about your resume.")
    from app.services.privacy import ai_allowed

    posting = db.get(JobPosting, version.job_posting_id) if version.job_posting_id else None
    profile = get_profile(db, user)
    private = posting is not None and not ai_allowed(db, user.id, posting)
    try:
        with ai_scope(user.id, "resume_chat", db):
            new_content, turn = resume_chat.chat(content, profile, posting, payload.message, provider, private=private)
    except AIError as exc:
        raise error(502, "ai_error", str(exc)) from exc
    version.content_json = dumps(new_content)
    if turn["applied"]:
        version.content_text = document_text(new_content["document"])
        _resume_edited(db, user, version)
    db.commit()
    return {**_version_out(version, include_content=True), "turn": turn}


@router.post("/resume-versions/{version_id}/undo")
def undo_chat_change(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services import resume_chat

    version = _owned_version(db, user, version_id)
    restored = resume_chat.undo(loads(version.content_json, {}))
    if restored is None:
        raise error(400, "nothing_to_undo", "There is no change to undo.")
    version.content_json = dumps(restored)
    version.content_text = document_text(restored["document"])
    _resume_edited(db, user, version)
    db.commit()
    return _version_out(version, include_content=True)


@router.post("/resume-versions/{version_id}/approve")
def approve_version(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """You checked this exact resume. Any later edit clears this, so an unreviewed version is never used."""
    version = _owned_version(db, user, version_id)
    if version.kind != "tailored":
        raise error(400, "not_tailored", "Only resumes tailored for a job are approved here.")
    version.approved_by_user = True
    db.commit()
    return _version_out(version, include_content=True)


@router.post("/resume-versions/{version_id}/regenerate", status_code=201)
def regenerate(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    version = _owned_version(db, user, version_id)
    posting = db.get(JobPosting, version.job_posting_id) if version.job_posting_id else None
    if posting is None:
        raise error(400, "no_job", "Only tailored versions can be regenerated.")
    # Regenerating is an explicit request for a new draft, so it skips the cached proposal.
    new_version = create_tailored_version(db, user, posting, fresh=True)
    for application in _applications_using(db, user.id, version.id):
        if application.status not in {"submitted", "interview", "offer", "rejected", "withdrawn"}:
            application.resume_version_id = new_version.id
            invalidate_approval(db, application, "A new resume version was generated.")
    db.commit()
    return _version_out(new_version, include_content=True)


@router.get("/resume-versions/{version_id}/compare")
def compare(version_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    version = _owned_version(db, user, version_id)
    tailored = loads(version.content_json, {})
    if tailored.get("format") == "document":
        return {
            "format": "document",
            "original": tailored.get("original_document"),
            "tailored": tailored.get("document"),
            "changes": tailored.get("changes", []),
            "keywords": tailored.get("keywords", {}),
            "generation": tailored.get("generation", {}),
            "fit": tailored.get("fit", {}),
            "source_resume_id": tailored.get("source_resume_id"),
        }
    base = db.scalar(
        select(ResumeVersion)
        .where(ResumeVersion.user_id == user.id, ResumeVersion.kind == "base")
        .order_by(ResumeVersion.created_at.desc())
    )
    original = loads(base.content_json, {}) if base else {"skills": [], "experience": []}
    if original.get("format") == "document":
        original = {"skills": [], "experience": []}
    return {"format": "legacy", "original": original, "tailored": tailored, "diff": compare_resumes(original, tailored)}


@router.get("/resume-versions/{version_id}/download")
def download(version_id: str, format: str = "docx", inline: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    version = _owned_version(db, user, version_id)
    content = loads(version.content_json, {})
    profile = get_profile(db, user)
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", f"{profile.user.full_name} {version.title}").strip("_")[:90] or "resume"
    if format not in {"pdf", "docx"}:
        raise error(400, "invalid_format", "Download format must be pdf or docx.")
    if content.get("format") == "document":
        contact = content.get("contact_overrides") or _contact(profile)
        if format == "pdf":
            data, _fit = render_document_pdf(content["document"], content.get("style"), contact_overrides=contact, title=version.title)
        else:
            data = None
            source = db.get(OriginalResume, content.get("source_resume_id")) if content.get("source_resume_id") else None
            if source is not None and source.storage_path.lower().endswith(".docx") and Path(source.storage_path).exists():
                data = edit_original_docx(Path(source.storage_path), content.get("original_document") or {}, content["document"])
            if data is None:
                data = render_document_docx(content["document"], content.get("style"), contact_overrides=contact)
    elif format == "pdf":
        data = render_pdf(content)
    else:
        data = render_docx(content)
    media = "application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    disposition = "inline" if inline and format == "pdf" else "attachment"
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'{disposition}; filename="{safe_name}.{format}"'})


def _contact(profile) -> dict:
    return {"linkedin_url": profile.linkedin_url, "github_url": profile.github_url, "portfolio_url": profile.portfolio_url}


def _owned_version(db: Session, user: User, version_id: str) -> ResumeVersion:
    version = db.get(ResumeVersion, version_id)
    if version is None or version.user_id != user.id:
        raise not_found()
    return version


def _applications_using(db: Session, user_id: str, version_id: str):
    return db.scalars(
        select(Application).where(Application.user_id == user_id, Application.resume_version_id == version_id)
    ).all()


def _resume_out(resume: OriginalResume, include_document: bool = False, primary_id: str | None = None) -> dict:
    payload = {
        "id": resume.id,
        "filename": resume.filename,
        "content_type": resume.content_type,
        "parse_status": resume.parse_status,
        "size_bytes": resume.size_bytes,
        "review_notes": resume.review_notes,
        "parser": resume.parser,
        "is_primary": bool(resume.is_primary) if primary_id is None else resume.id == primary_id,
        "extraction": loads(resume.extracted_json, {}),
        "approved_at": resume.approved_at.isoformat() if resume.approved_at else None,
        "created_at": resume.created_at.isoformat() if resume.created_at else None,
        "has_layout": bool(resume.document_json),
    }
    if include_document:
        payload["document"] = loads(resume.document_json, None)
        payload["style"] = loads(resume.style_json, None)
    return payload


def _version_out(version: ResumeVersion, include_content: bool = False) -> dict:
    content = loads(version.content_json, {}) if include_content or True else {}
    payload = {
        "id": version.id,
        "job_posting_id": version.job_posting_id,
        "kind": version.kind,
        "template": version.template,
        "length": version.length,
        "title": version.title,
        "format": content.get("format", "legacy"),
        "generation": content.get("generation"),
        "keywords": content.get("keywords"),
        "change_count": len(content.get("changes") or []),
        "approved_by_user": bool(version.approved_by_user),
        "private_job": bool((content.get("generation") or {}).get("private")),
        "can_undo": bool(content.get("history")),
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }
    if include_content:
        payload["content"] = content
        payload["text"] = version.content_text
    return payload


__all__ = ["router", "create_tailored_version", "TruthfulnessError"]
