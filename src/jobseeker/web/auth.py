from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from jobseeker.db.sessions import create_session, delete_session, delete_user_sessions, purge_expired
from jobseeker.db.users import EmailLinkedElsewhere, owner_first_name, resolve_sign_in
from jobseeker.web.deps import get_conn, optional_user, render_public
from jobseeker.web.oauth import (OAUTH_COOKIE, SESSION_COOKIE, TOKEN_URL, BadSignature, auth_url, local_path,
                                 pkce_pair, sign, unsign)

router = APIRouter()
SESSION_MAX_AGE = 30 * 24 * 3600


def exchange_code(settings, code: str, verifier: str, redirect_path: str = "/auth/callback") -> dict:
    r = httpx.post(TOKEN_URL, timeout=10, data={
        "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "redirect_uri": f"{settings.base_url}{redirect_path}", "grant_type": "authorization_code",
        "code_verifier": verifier})
    r.raise_for_status()
    return r.json()


def verify_id_token(token: str, client_id: str) -> dict:
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, GoogleRequest(), client_id)  # signature, aud, iss, exp


def _page(request, status: int, message: str, conn=None, note: str = ""):
    if status == 403:
        return render_public(request, conn, "landing.html", status_code=403, owner_first=owner_first_name(conn),
                             invite_only=True, note=note)
    return request.app.state.templates.TemplateResponse(request, "auth_message.html", {"message": message},
                                                        status_code=status)


def _cookie(resp, name: str, value: str, max_age: int, settings) -> None:
    resp.set_cookie(name, value, max_age=max_age, path="/", secure=settings.cookie_secure, httponly=True,
                    samesite="lax")


@router.get("/login")
def login(request: Request, next: str = ""):
    s, now = request.app.state.settings, datetime.now(UTC)
    verifier, challenge = pkce_pair()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    resp = RedirectResponse(auth_url(s.google_client_id, f"{s.base_url}/auth/callback", state, nonce, challenge), 303)
    payload = {"state": state, "nonce": nonce, "verifier": verifier, "next": local_path(next) or "/"}
    _cookie(resp, OAUTH_COOKIE, sign(payload, s.secret_key, now, timedelta(minutes=10)), 600, s)
    return resp


@router.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "", conn=Depends(get_conn)):
    resp = _callback(request, code, state, error, conn)
    s = request.app.state.settings  # the OAuth cookie is single-use: cleared on every exit, not only success
    resp.delete_cookie(OAUTH_COOKIE, path="/", secure=s.cookie_secure, httponly=True, samesite="lax")
    return resp


def _callback(request: Request, code: str, state: str, error: str, conn):
    s, now = request.app.state.settings, datetime.now(UTC)
    if error:
        return _page(request, 200, "Sign-in was cancelled.")
    try:
        data = unsign(request.cookies.get(OAUTH_COOKIE, ""), s.secret_key, now)
    except BadSignature:
        return _page(request, 400, "Sign-in expired, try again.")
    if not state or not secrets.compare_digest(state, data.get("state", "")):
        return _page(request, 400, "Sign-in expired, try again.")
    try:
        token = exchange_code(s, code, data["verifier"])["id_token"]
    except (httpx.HTTPError, KeyError, ValueError):
        return _page(request, 502, "Couldn't reach Google, try again.")
    try:
        claims = verify_id_token(token, s.google_client_id)
    except Exception:  # google-auth raises ValueError and friends for bad tokens
        return _page(request, 400, "Sign-in couldn't be verified.")
    if claims.get("nonce") != data.get("nonce") or claims.get("email_verified") is not True:
        return _page(request, 400, "Sign-in couldn't be verified.")
    try:
        user = resolve_sign_in(conn, claims["sub"], claims.get("email", ""), claims.get("name", ""), now)
    except EmailLinkedElsewhere:
        conn.rollback()
        return _page(request, 403, "", conn, note="This email is already linked to a different Google account. "
                                                  "Ask the owner to sort it out.")
    if user is None:
        return _page(request, 403, "This app is invite-only.", conn)
    if secrets.randbelow(100) == 0:
        purge_expired(conn, now)
    resp = RedirectResponse(local_path(data.get("next")) or "/", 303)
    _cookie(resp, SESSION_COOKIE, create_session(conn, user.id, now), SESSION_MAX_AGE, s)
    return resp


def _signed_out(request):
    resp = RedirectResponse("/login", 303)
    s = request.app.state.settings
    resp.delete_cookie(SESSION_COOKIE, path="/", secure=s.cookie_secure, httponly=True, samesite="lax")
    return resp


@router.post("/logout")
def logout(request: Request, conn=Depends(get_conn)):
    delete_session(conn, request.cookies.get(SESSION_COOKIE, ""))
    return _signed_out(request)


@router.post("/logout/all")
def logout_all(request: Request, user=Depends(optional_user), conn=Depends(get_conn)):
    if user is not None:
        delete_user_sessions(conn, user.id)
    return _signed_out(request)
