from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path


def build_raw_message(*, to: str, subject: str, body: str, attachment: Path | None,
                      attachment_name: str) -> str:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment is not None:
        msg.add_attachment(Path(attachment).read_bytes(), maintype="application", subtype="pdf",
                           filename=attachment_name)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
