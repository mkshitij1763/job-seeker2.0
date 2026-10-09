import html
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from jobseeker.db.core import connect
from jobseeker.db.gmail_tokens import load_token, save_token, token_info
from jobseeker.gmail.client import GmailUnavailable, load_service
from jobseeker.web import auth, oauth

T = datetime(2026, 10, 9, tzinfo=UTC)
CREDS = json.dumps({"token": "at", "refresh_token": "rt", "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": "cid", "client_secret": "s", "scopes": ["https://www.googleapis.com/auth/gmail.compose"]})


def _connect(web, next_="/applications/1"):
    r = web.get(f"/gmail/connect?next={next_}")
    assert r.status_code == 303
    return parse_qs(urlsplit(r.headers["location"]).query)


def test_connect_redirect_asks_for_compose_offline_with_login_hint(client_as):
    q = _connect(client_as(1, follow_redirects=False))
    assert q["scope"] == ["openid email https://www.googleapis.com/auth/gmail.compose"]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"] and q["login_hint"] == ["owner@example.com"]
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"][0].endswith("/gmail/callback")


def test_sign_in_never_asks_for_gmail(client_as, anon_client):
    loc = anon_client().get("/login").headers["location"]
    assert "gmail" not in parse_qs(urlsplit(loc).query)["scope"][0]


def test_callback_stores_sealed_token_for_the_account_google_returned(client_as, settings, monkeypatch):
    web = client_as(1, follow_redirects=False)
    q = _connect(web)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": q["nonce"][0], "email": "other@gmail.com",
                                                                    "email_verified": True, "sub": "g"})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={
            "id_token": "x", "access_token": "at", "refresh_token": "rt", "expires_in": 3600}))
        r = web.get(f"/gmail/callback?code=c&state={q['state'][0]}")
    assert r.status_code == 303 and r.headers["location"].startswith("/applications/1")
    conn = connect(settings.db_path)
    assert token_info(conn, 1)["account_email"] == "other@gmail.com"      # drafts go where Google said
    blob = conn.execute("SELECT token_enc FROM gmail_tokens WHERE user_id = 1").fetchone()[0]
    assert b"rt" not in blob
    assert json.loads(load_token(conn, web.app.state.token_key, 1))["refresh_token"] == "rt"


def test_callback_without_refresh_token_is_refused(client_as, settings, monkeypatch):
    web = client_as(1, follow_redirects=False)
    q = _connect(web)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": q["nonce"][0], "email": "o@gmail.com",
                                                                    "email_verified": True, "sub": "g"})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x", "access_token": "at"}))
        r = web.get(f"/gmail/callback?code=c&state={q['state'][0]}")
    assert "Google didn't grant offline access" in html.unescape(r.text) and token_info(connect(settings.db_path), 1) is None


def test_row_moved_to_another_user_needs_reconnect(settings, client_as):
    key = client_as(1).app.state.token_key
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    save_token(conn, key, 1, "o@gmail.com", CREDS, T)
    blob = conn.execute("SELECT token_enc FROM gmail_tokens WHERE user_id = 1").fetchone()[0]
    conn.execute("INSERT INTO gmail_tokens (user_id, account_email, token_enc, connected_at) VALUES (2, 'x', ?, 't')",
                 (blob,))
    with pytest.raises(GmailUnavailable) as e:
        load_service(conn, 2, key)
    assert e.value.reconnect and token_info(conn, 2)["status"] == "expired"


def test_refresh_writes_back_and_invalid_grant_expires(settings, client_as, monkeypatch):
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    key = client_as(1).app.state.token_key
    conn = connect(settings.db_path)
    save_token(conn, key, 1, "o@gmail.com", CREDS, T)
    before = conn.execute("SELECT token_enc FROM gmail_tokens WHERE user_id = 1").fetchone()[0]
    monkeypatch.setattr(Credentials, "valid", property(lambda self: self.token == "fresh"))
    monkeypatch.setattr(Credentials, "refresh", lambda self, req: setattr(self, "token", "fresh"))
    load_service(conn, 1, key)
    after = conn.execute("SELECT token_enc, refreshed_at FROM gmail_tokens WHERE user_id = 1").fetchone()
    assert after[0] != before and after[1]
    monkeypatch.setattr(Credentials, "valid", property(lambda self: False))

    def bad(self, req):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")
    monkeypatch.setattr(Credentials, "refresh", bad)
    with pytest.raises(GmailUnavailable) as e:
        load_service(conn, 1, key)
    assert e.value.reconnect and token_info(conn, 1)["status"] == "expired"


def test_approve_with_expired_token_offers_reconnect_to_the_same_job(seeded, client_as, settings):
    from jobseeker.db.applications import save_contact, save_draft
    conn = connect(settings.db_path)
    save_draft(conn, seeded[0], "email", "S", "B")
    save_contact(conn, seeded[0], name="Rohan Mehta", role="PM", linkedin_url="", email="rohan@cred.club",
                 email_status="verified")
    conn.execute("UPDATE applications SET status = 'drafted' WHERE id = ?", (seeded[0],))
    conn.commit()

    def expired(c, uid):
        raise GmailUnavailable("Gmail needs reconnecting", reconnect=True)
    web = client_as(1, gmail_factory=expired, follow_redirects=False)
    r = web.post(f"/applications/{seeded[0]}/approve", data={"confirm_unverified": "true"})
    page = web.get(r.headers["location"]).text
    assert f'/gmail/connect?next=/applications/{seeded[0]}' in page and "Reconnect Gmail" in page


def test_settings_card_shows_the_connected_account(settings, client_as):
    key = client_as(1).app.state.token_key
    conn = connect(settings.db_path)
    page = html.unescape(client_as(1).get("/settings").text)
    assert "Connect Gmail" in page and "isn't verified" in page
    save_token(conn, key, 1, "o@gmail.com", CREDS, T)
    assert "Drafts go to o@gmail.com" in client_as(1).get("/settings").text


def test_auth_gmail_command_is_gone():
    from typer.testing import CliRunner

    from jobseeker.cli import app
    assert CliRunner().invoke(app, ["auth-gmail"]).exit_code != 0


def test_turning_outreach_off_deletes_the_grant(settings, client_as):
    from jobseeker.db.users import set_outreach
    key = client_as(1).app.state.token_key
    conn = connect(settings.db_path)
    save_token(conn, key, 1, "o@gmail.com", CREDS, T)
    set_outreach(conn, 1, False)
    assert token_info(conn, 1) is None
