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


def test_load_service_without_token_needs_connecting(settings):
    from jobseeker.db.core import connect
    with pytest.raises(GmailUnavailable) as e:
        load_service(connect(settings.db_path), 1, b"k" * 32)
    assert e.value.reconnect


def test_create_draft_returns_id():
    calls = {}

    class Drafts:
        def create(self, userId, body):
            calls["body"] = body
            return SimpleNamespace(execute=lambda: {"id": "r-123", "message": {"id": "m1"}})

    service = SimpleNamespace(users=lambda: SimpleNamespace(drafts=lambda: Drafts()))
    assert create_draft(service, "cmF3") == "r-123"
    assert calls["body"] == {"message": {"raw": "cmF3"}}


def test_load_service_with_undecryptable_token_needs_reconnecting(settings):
    from jobseeker.db.core import connect
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO gmail_tokens (user_id, account_email, token_enc, connected_at) VALUES (1, 'o', ?, 't')",
                 (b"garbage" * 8,))
    with pytest.raises(GmailUnavailable) as e:
        load_service(conn, 1, b"k" * 32)
    assert e.value.reconnect


def test_create_draft_401_needs_reconnecting():
    from googleapiclient.errors import HttpError

    def denied():
        raise HttpError(SimpleNamespace(status=401, reason="Unauthorized"), b"{}")

    class Drafts:
        def create(self, userId, body):
            return SimpleNamespace(execute=denied)

    service = SimpleNamespace(users=lambda: SimpleNamespace(drafts=lambda: Drafts()))
    with pytest.raises(GmailUnavailable) as e:
        create_draft(service, "cmF3")
    assert e.value.reconnect


@pytest.mark.parametrize("error", [OSError("network down"), "transport"])
def test_create_draft_network_failure_is_unavailable(error):
    from google.auth.exceptions import TransportError

    exc = TransportError("offline") if error == "transport" else error

    def boom():
        raise exc

    class Drafts:
        def create(self, userId, body):
            return SimpleNamespace(execute=boom)

    service = SimpleNamespace(users=lambda: SimpleNamespace(drafts=lambda: Drafts()))
    with pytest.raises(GmailUnavailable, match="reach Gmail"):
        create_draft(service, "cmF3")


@pytest.mark.parametrize(("status", "reason", "reconnect"), [
    (403, "rateLimitExceeded", False), (403, "userRateLimitExceeded", False), (403, "accessNotConfigured", False),
    (403, "insufficientPermissions", True), (403, "authError", True), (401, "authError", True)])
def test_review_6_only_auth_failures_need_reconnecting(status, reason, reconnect):
    import json as _json

    from googleapiclient.errors import HttpError
    body = _json.dumps({"error": {"code": status, "errors": [{"reason": reason}]}}).encode()

    def fails():
        raise HttpError(SimpleNamespace(status=status, reason="x"), body)

    class Drafts:
        def create(self, userId, body):
            return SimpleNamespace(execute=fails)

    with pytest.raises(GmailUnavailable) as e:
        create_draft(SimpleNamespace(users=lambda: SimpleNamespace(drafts=lambda: Drafts())), "cmF3")
    assert e.value.reconnect is reconnect
