from pathlib import Path

import fitz


def extract_text(pdf_path: Path | str) -> str:
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc).strip()
