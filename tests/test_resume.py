import fitz
import pytest

from jobseeker.profile.resume import MAX_BYTES, ResumeRejected, store_resume, validate_pdf

GOOD = "Asha Owner — Product Analyst. " * 20


def pdf_bytes(text=GOOD, pages=1):
    doc = fitz.open()
    lines = [text[i:i + 60] for i in range(0, len(text), 60)]  # short lines: insert_text doesn't wrap
    for _ in range(pages):
        page = doc.new_page()
        for n, line in enumerate(lines):
            page.insert_text((72, 72 + 14 * n), line)
    return doc.tobytes()


def test_good_pdf_returns_text():
    assert "Product Analyst" in validate_pdf(pdf_bytes(), "application/pdf")


@pytest.mark.parametrize("data,ctype,msg", [
    (b"\x89PNG....", "application/pdf", "as a PDF"),
    (pdf_bytes(), "image/png", "as a PDF"),
    (b"%PDF-1.4 broken", "application/pdf", "couldn't be read"),
    (pdf_bytes(pages=11), "application/pdf", "over 10 pages"),
    (pdf_bytes(text="hi"), "application/pdf", "scanned PDF"),
    (b"%PDF-" + b"0" * MAX_BYTES, "application/pdf", "over 5 MB"),
])
def test_rejections(data, ctype, msg):
    with pytest.raises(ResumeRejected, match=msg):
        validate_pdf(data, ctype)


def test_store_resume_modes_and_atomic(tmp_path):
    path, sha = store_resume(tmp_path, 7, pdf_bytes())
    assert path == tmp_path / "data" / "users" / "7" / "resume.pdf" and len(sha) == 64
    assert oct(path.stat().st_mode)[-3:] == "600" and oct(path.parent.stat().st_mode)[-3:] == "700"
    assert not (path.parent / "resume.pdf.tmp").exists()
