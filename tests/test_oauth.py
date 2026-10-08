import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from jobseeker.web import oauth

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def test_sign_roundtrip_and_expiry():
    tok = oauth.sign({"state": "s"}, "k" * 32, NOW, timedelta(minutes=10))
    assert oauth.unsign(tok, "k" * 32, NOW + timedelta(minutes=9))["state"] == "s"
    with pytest.raises(oauth.BadSignature):
        oauth.unsign(tok, "k" * 32, NOW + timedelta(minutes=11))


@pytest.mark.parametrize("tamper", [lambda t: t[:-2] + "xx", lambda t: "e30" + t[3:], lambda t: "", lambda t: "nodot"])
def test_unsign_rejects_tampering(tamper):
    tok = oauth.sign({"state": "s"}, "k" * 32, NOW, timedelta(minutes=10))
    with pytest.raises(oauth.BadSignature):
        oauth.unsign(tamper(tok), "k" * 32, NOW)


def test_unsign_rejects_other_key():
    tok = oauth.sign({"state": "s"}, "k" * 32, NOW, timedelta(minutes=10))
    with pytest.raises(oauth.BadSignature):
        oauth.unsign(tok, "j" * 32, NOW)


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = oauth.pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected and len(verifier) >= 43


def test_auth_url_has_exact_params():
    q = parse_qs(urlsplit(oauth.auth_url("cid", "https://x/auth/callback", "st", "no", "ch")).query)
    assert q["scope"] == ["openid email profile"] and q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["st"] and q["nonce"] == ["no"] and q["response_type"] == ["code"]
    assert q["prompt"] == ["select_account"] and q["redirect_uri"] == ["https://x/auth/callback"]


@pytest.mark.parametrize("value,expected", [("/applications/3?x=1", "/applications/3?x=1"), ("//evil.com", None),
                                            ("https://evil.com", None), ("/\\evil", None), ("", None), (None, None)])
def test_local_path(value, expected):
    assert oauth.local_path(value) == expected
