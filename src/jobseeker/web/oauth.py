"""Pure helpers for the hand-rolled Google sign-in: signed short-lived cookies, PKCE, the auth URL."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SESSION_COOKIE = "__Host-js_session"
OAUTH_COOKIE = "__Host-js_oauth"


class BadSignature(ValueError):
    pass


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _mac(body: str, key: str) -> str:
    return _b64(hmac.new(key.encode(), body.encode(), hashlib.sha256).digest())


def sign(payload: dict, key: str, now: datetime, ttl: timedelta) -> str:
    body = _b64(json.dumps({**payload, "exp": int((now + ttl).timestamp())}, separators=(",", ":")).encode())
    return f"{body}.{_mac(body, key)}"


def unsign(token: str, key: str, now: datetime) -> dict:
    body, dot, mac = (token or "").partition(".")
    if not dot or not hmac.compare_digest(mac, _mac(body, key)):
        raise BadSignature("bad signature")
    try:
        data = json.loads(_unb64(body))
    except ValueError as e:
        raise BadSignature("unreadable") from e
    if not isinstance(data, dict) or data.get("exp", 0) < now.timestamp():
        raise BadSignature("expired")
    return data


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    return verifier, _b64(hashlib.sha256(verifier.encode()).digest())


def auth_url(client_id: str, redirect_uri: str, state: str, nonce: str, challenge: str,
             scope: str = "openid email profile", **extra: str) -> str:
    q = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": scope,
         "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
         "prompt": "select_account", **extra}
    return f"{AUTH_URL}?{urlencode(q)}"


def local_path(next_: str | None) -> str | None:
    """Only same-site paths: "//host" and "/\\host" leave the site."""
    if next_ and next_.startswith("/") and not next_.startswith(("//", "/\\")):
        return next_
    return None
