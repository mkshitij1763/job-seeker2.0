from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from jobseeker.db.core import connect
from jobseeker.db.sessions import create_session, user_for_token
from jobseeker.db.users import add_invite
from jobseeker.web import auth, oauth
from jobseeker.web.app import create_app

T = datetime(2026, 10, 8, tzinfo=UTC)


@pytest.fixture
def web(settings):
    return TestClient(create_app(settings), base_url="https://testserver", follow_redirects=False)


def _login(web, next_="/"):
    r = web.get(f"/login?next={next_}")
    assert r.status_code == 303
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return q["state"][0], q["nonce"][0]


def _callback(web, monkeypatch, claims, state=None):
    st, nonce = _login(web)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": nonce, "email_verified": True, **claims})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x"}))
        return web.get(f"/auth/callback?code=c&state={state or st}")


def test_login_redirect_and_cookie(web):
    r = web.get("/login?next=/pipeline")
    loc = urlsplit(r.headers["location"])
    assert loc.netloc == "accounts.google.com"
    assert "__Host-js_oauth" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]


def test_owner_signs_in(web, monkeypatch):
    r = _callback(web, monkeypatch, {"sub": "g1", "email": "owner@example.com", "name": "Kay Em"})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "__Host-js_session" in r.headers["set-cookie"]


def test_state_mismatch_is_400(web, monkeypatch):
    assert _callback(web, monkeypatch, {"sub": "g1", "email": "owner@example.com"}, state="wrong").status_code == 400


def test_nonce_or_unverified_email_refused(web, monkeypatch):
    st, _ = _login(web)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": "other", "email_verified": True,
                                                                    "sub": "g1", "email": "owner@example.com"})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x"}))
        assert web.get(f"/auth/callback?code=c&state={st}").status_code == 400
    r = _callback(web, monkeypatch, {"sub": "g1", "email": "owner@example.com", "email_verified": False})
    assert r.status_code == 400


def test_verify_failure_and_token_endpoint_failure(web, monkeypatch):
    st, _ = _login(web)

    def boom(tok, cid):
        raise ValueError("bad aud")
    monkeypatch.setattr(auth, "verify_id_token", boom)
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x"}))
        assert web.get(f"/auth/callback?code=c&state={st}").status_code == 400
    st, _ = _login(web)
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(side_effect=httpx.ConnectError("down"))
        assert web.get(f"/auth/callback?code=c&state={st}").status_code == 502


def test_uninvited_gets_403_with_owner_name_and_no_row(web, monkeypatch, settings):
    r = _callback(web, monkeypatch, {"sub": "g9", "email": "stranger@example.com"})
    assert r.status_code == 403 and "invite-only" in r.text and "Kshitij" not in r.text
    assert connect(settings.db_path).execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_invited_user_signs_in(web, monkeypatch, settings):
    add_invite(connect(settings.db_path), "roomie@example.com", 1, T)
    assert _callback(web, monkeypatch, {"sub": "g2", "email": "roomie@example.com"}).status_code == 303


@pytest.mark.parametrize("bad", ["//evil.com", "https://evil.com", "/\\evil"])
def test_next_open_redirects_fall_back(web, monkeypatch, bad):
    st, nonce = _login(web, bad)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": nonce, "email_verified": True,
                                                                    "sub": "g1", "email": "owner@example.com"})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x"}))
        assert web.get(f"/auth/callback?code=c&state={st}").headers["location"] == "/"


def test_session_sliding_writes_at_most_daily(settings):
    conn = connect(settings.db_path)
    tok = create_session(conn, 1, T)
    assert user_for_token(conn, tok, T + timedelta(hours=1))[1] is False
    user, refreshed = user_for_token(conn, tok, T + timedelta(hours=25))
    assert refreshed and user.id == 1
    assert user_for_token(conn, tok, T + timedelta(days=60)) is None
    assert user_for_token(conn, "forged", T) is None


def test_disabled_user_session_is_signed_out(settings):
    conn = connect(settings.db_path)
    tok = create_session(conn, 1, T)
    conn.execute("UPDATE users SET disabled_at = 't' WHERE id = 1")
    conn.commit()
    assert user_for_token(conn, tok, T) is None


def test_logout_deletes_session(web, settings):
    conn = connect(settings.db_path)
    tok = create_session(conn, 1, datetime.now(UTC))
    web.cookies.set("__Host-js_session", tok)
    r = web.post("/logout", headers={"Origin": "https://testserver"})
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_startup_refuses_missing_auth_settings(settings):
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        create_app(settings.model_copy(update={"google_client_id": ""}))
