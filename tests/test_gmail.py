import base64
import email
from types import SimpleNamespace

import pytest

from jobseeker.gmail.client import SCOPES, GmailUnavailable, create_draft, load_service
from jobseeker.gmail.mime import build_raw_message


def test_scope_is_compose_only():
    assert SCOPES == ["https://www.googleapis.com/auth/gmail.compose"]


def test_build_raw_message_with_attachment(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.5 fake")
    raw = build_raw_message(to="asha@cred.club", subject="Hello", body="Body text", attachment=pdf,
                            attachment_name="Kshitij_Meshram_Resume.pdf")
    msg = email.message_from_bytes(base64.urlsafe_b64decode(raw))
    assert msg["To"] == "asha@cred.club" and msg["Subject"] == "Hello"
    parts = list(msg.walk())
    assert any(p.get_filename() == "Kshitij_Meshram_Resume.pdf" for p in parts)
    assert any(p.get_content_type() == "text/plain" and "Body text" in p.get_payload(decode=True).decode() for p in parts)


def test_load_service_without_token(tmp_path):
    with pytest.raises(GmailUnavailable):
        load_service(tmp_path / "token.json")


def test_create_draft_returns_id():
    calls = {}

    class Drafts:
        def create(self, userId, body):
            calls["body"] = body
            return SimpleNamespace(execute=lambda: {"id": "r-123", "message": {"id": "m1"}})

    service = SimpleNamespace(users=lambda: SimpleNamespace(drafts=lambda: Drafts()))
    assert create_draft(service, "cmF3") == "r-123"
    assert calls["body"] == {"message": {"raw": "cmF3"}}
