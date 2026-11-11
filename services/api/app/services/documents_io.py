import io
import zipfile
from pathlib import Path

from docx import Document
from pypdf import PdfReader


class DocumentError(Exception):
    pass


def extract_text(path: Path, content_type: str) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf" or "pdf" in content_type:
        return _pdf_text(path)
    if suffix == ".docx" or "wordprocessingml" in content_type:
        return _docx_text(path)
    raise DocumentError("Only PDF and DOCX resumes are supported.")


def _pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        raise DocumentError("The PDF could not be read. It may be encrypted or damaged.") from exc
    if reader.is_encrypted:
        raise DocumentError("Password-protected PDFs are not supported.")
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def _docx_text(path: Path) -> str:
    if not zipfile.is_zipfile(path):
        raise DocumentError("The DOCX file is not a valid document.")
    document = Document(str(path))
    lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    return "\n".join(lines).strip()


def validate_upload(filename: str, content_type: str, data: bytes, max_bytes: int) -> str:
    if len(data) > max_bytes:
        raise DocumentError("File exceeds the 8 MB upload limit.")
    if len(data) < 32:
        raise DocumentError("File is empty.")
    lower = filename.lower()
    if lower.endswith(".pdf") or content_type == "application/pdf":
        if not data.startswith(b"%PDF"):
            raise DocumentError("File does not look like a PDF.")
        return ".pdf"
    docx_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lower.endswith(".docx") or content_type == docx_type:
        if not data.startswith(b"PK"):
            raise DocumentError("File does not look like a DOCX document.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise DocumentError("DOCX archive is missing document content.")
        except zipfile.BadZipFile as exc:
            raise DocumentError("DOCX archive is invalid.") from exc
        return ".docx"
    raise DocumentError("Upload a PDF or DOCX resume.")
