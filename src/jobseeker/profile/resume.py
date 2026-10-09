import hashlib
import os
from pathlib import Path

import fitz


def extract_text(pdf_path: Path | str) -> str:
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc).strip()


def resume_path(home: Path, user_id: int) -> Path:
    return home / "data" / "users" / str(user_id) / "resume.pdf"


MAX_BYTES, MAX_PAGES, MIN_CHARS = 5 * 1024 * 1024, 10, 300


class ResumeRejected(ValueError):
    pass


def validate_pdf(data: bytes, content_type: str) -> str:
    if len(data) > MAX_BYTES:
        raise ResumeRejected("That file is over 5 MB. Export a smaller PDF.")
    if content_type != "application/pdf" or not data.startswith(b"%PDF-"):
        raise ResumeRejected("Please upload your resume as a PDF.")
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.page_count == 0:
                raise ResumeRejected("That PDF couldn't be read. Try exporting it again.")
            if doc.page_count > MAX_PAGES:
                raise ResumeRejected("Resumes over 10 pages aren't supported.")
            text = "\n".join(p.get_text() for p in doc).strip()
    except ResumeRejected:
        raise
    except Exception as e:  # PyMuPDF raises its own error types for broken files
        raise ResumeRejected("That PDF couldn't be read. Try exporting it again.") from e
    if len(text) < MIN_CHARS:
        raise ResumeRejected("This looks like a scanned PDF. Export a text PDF from Word or Google Docs.")
    return text


def store_resume(home: Path, user_id: int, data: bytes) -> tuple[Path, str]:
    path = resume_path(home, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".pdf.tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return path, hashlib.sha256(data).hexdigest()
