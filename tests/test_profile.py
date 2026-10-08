import fitz

from jobseeker.profile.resume import extract_text


def _pdf(path, text="Kshitij Meshram\nProduct Analyst at Inito\nCut errors by 67%"):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(path)


def test_extract_text(tmp_path):
    p = tmp_path / "r.pdf"
    _pdf(p)
    assert "Cut errors by 67%" in extract_text(p)
