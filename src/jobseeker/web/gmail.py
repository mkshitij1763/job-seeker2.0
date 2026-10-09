"""Connect a user's own Gmail: a separate consent (gmail.compose, offline) from sign-in, on the same Web client."""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from google.auth.exceptions import GoogleAuthError

from jobseeker.db.gmail_tokens import save_token
from jobseeker.gmail.client import SCOPES
from jobseeker.web import auth
from jobseeker.web.deps import get_conn, require_outreach
from jobseeker.web.oauth import BadSignature, auth_url, local_path, pkce_pair, sign, unsign

router = APIRouter(prefix="/gmail")
GMAIL_COOKIE = "__Host-js_gmail_oauth"
SCOPE = "openid email " + " ".join(SCOPES)


@router.get("/connect")
def connect(request: Request, next: str = "", user=Depends(require_outreach)):
    s, now = request.app.state.settings, datetime.now(UTC)
    verifier, challenge = pkce_pair()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    url = auth_url(s.google_client_id, f"{s.base_url}/gmail/callback", state, nonce, challenge, scope=SCOPE,
                   access_type="offline", prompt="consent", include_granted_scopes="false", login_hint=user.email)
    resp = RedirectResponse(url, 303)
    payload = {"state": state, "nonce": nonce, "verifier": verifier, "next": local_path(next) or "/settings",
               "uid": user.id}
    resp.set_cookie(GMAIL_COOKIE, sign(payload, s.secret_key, now, timedelta(minutes=10)), max_age=600, path="/",
                    secure=s.cookie_secure, httponly=True, samesite="lax")
    return resp


def _fail(request, message: str):
    return request.app.state.templates.TemplateResponse(
        request, "auth_message.html", {"message": message, "retry": "/gmail/connect", "heading": "Connect Gmail"},
        status_code=400)


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "", user=Depends(require_outreach),
             conn=Depends(get_conn)):
    s, now = request.app.state.settings, datetime.now(UTC)
    try:
        data = unsign(request.cookies.get(GMAIL_COOKIE, ""), s.secret_key, now)
    except BadSignature:
        data = {}
    if error or not state or not secrets.compare_digest(state, data.get("state", "")) or data.get("uid") != user.id:
        resp = _fail(request, "Gmail connection expired. Try again")
    else:
        try:
            tokens = auth.exchange_code(s, code, data["verifier"], redirect_path="/gmail/callback")
            claims = auth.verify_id_token(tokens["id_token"], s.google_client_id)
        except (httpx.HTTPError, KeyError, ValueError, GoogleAuthError):
            resp = _fail(request, "Couldn't reach Google, try again.")
        else:
            if claims.get("nonce") != data.get("nonce"):
                resp = _fail(request, "Gmail connection couldn't be verified. Try again")
            elif not set(SCOPES) <= set(tokens.get("scope", "").split()):
                resp = _fail(request, "Gmail wasn't connected: tick the Compose permission "
                                      "(\"Manage drafts and send emails\") on Google's screen, then try again")
            elif not tokens.get("refresh_token"):
                resp = _fail(request, "Google didn't grant offline access. Try again")
            else:
                from google.oauth2.credentials import Credentials
                creds = Credentials(tokens["access_token"], refresh_token=tokens["refresh_token"],
                                    token_uri="https://oauth2.googleapis.com/token", client_id=s.google_client_id,
                                    client_secret=s.google_client_secret, scopes=SCOPES)
                email = claims.get("email", "")  # the account Google returned, which may not be the sign-in one
                save_token(conn, request.app.state.token_key, user.id, email, creds.to_json(), now)
                msg = quote(f"Gmail connected: drafts go to {email}")
                nxt = data["next"]
                resp = RedirectResponse(f"{nxt}{'&' if '?' in nxt else '?'}msg={msg}", 303)
    resp.delete_cookie(GMAIL_COOKIE, path="/", secure=s.cookie_secure, httponly=True, samesite="lax")
    return resp
