import base64
import json
import os
from datetime import UTC, datetime

import http_ece
import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02

from jobseeker.b64 import urlsafe_decode, urlsafe_encode
from jobseeker.push.send import VapidKeys, encrypt_payload, send_one, valid_keys, vapid_headers

NOW = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)
ENDPOINT = "https://web.push.apple.com/QGz123abc"


def _vapid() -> VapidKeys:
    v = Vapid02()
    v.generate_keys()
    priv = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return VapidKeys(private=urlsafe_encode(priv), public=urlsafe_encode(pub), subject="mailto:owner@example.com")


def _subscriber():
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    return key, urlsafe_encode(pub), urlsafe_encode(auth), auth


def test_payload_decrypts_for_the_subscriber():
    key, p256dh, auth_b64, auth = _subscriber()
    payload = {"title": "3 new matches", "body": "Top: 92 · Open Job Seeker", "url": "/?band=apply"}
    body = encrypt_payload(payload, p256dh, auth_b64)
    assert json.loads(http_ece.decrypt(body, private_key=key, auth_secret=auth, version="aes128gcm")) == payload


def test_vapid_header_claims():
    keys = _vapid()
    header = vapid_headers(ENDPOINT, keys, NOW)["Authorization"]
    assert header.startswith("vapid t=") and f"k={keys.public}" in header
    token = header.split("t=", 1)[1].split(",", 1)[0]
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert claims == {"aud": "https://web.push.apple.com", "exp": int(NOW.timestamp()) + 12 * 3600,
                      "sub": "mailto:owner@example.com"}


@respx.mock
def test_send_one_posts_encrypted_body_with_headers():
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(201))
    _, p256dh, auth_b64, _ = _subscriber()
    with httpx.Client() as client:
        status = send_one(client, ENDPOINT, p256dh, auth_b64, {"title": "t"}, _vapid(), NOW)
    req = route.calls.last.request
    assert status == 201
    assert req.headers["Content-Encoding"] == "aes128gcm" and req.headers["TTL"] == "86400"
    assert req.headers["Urgency"] == "normal" and req.headers["Authorization"].startswith("vapid t=")
    assert b"title" not in req.content  # encrypted


def test_valid_keys():
    _, p256dh, auth_b64, _ = _subscriber()
    assert valid_keys(p256dh, auth_b64)
    assert not valid_keys("abc", auth_b64) and not valid_keys(p256dh, "!!!") and not valid_keys(p256dh, "")
    assert len(urlsafe_decode(p256dh)) == 65


def test_endpoint_allow_list():
    from jobseeker.push.send import allowed_endpoint
    for ok in ("https://fcm.googleapis.com/fcm/send/abc", "https://updates.push.services.mozilla.com/wpush/v2/x",
               "https://web.push.apple.com/QGz", "https://wns2-par02p.notify.windows.com/w/?token=x"):
        assert allowed_endpoint(ok), ok
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example/x", "https://push.apple.com.evil.example/x",
                "https://fcm.googleapis.com:8443/x", "https://u@fcm.googleapis.com/x", "https://127.0.0.1/x",
                "https://localhost/x", "https://notify.windows.com/x", "https://xfcm.googleapis.com/x", "nonsense"):
        assert not allowed_endpoint(bad), bad


def test_valid_keys_rejects_a_point_off_the_curve():
    off_curve = urlsafe_encode(b"\x04" + b"\x01" * 64)
    assert not valid_keys(off_curve, urlsafe_encode(os.urandom(16)))


def test_send_one_refuses_bad_endpoint_or_key_without_a_request():
    import pytest

    from jobseeker.push.send import InvalidSubscription
    _, p256dh, auth, _ = _subscriber()
    with respx.mock(assert_all_called=False) as mock, httpx.Client() as client:
        route = mock.post(url__regex=r".*").respond(201)
        with pytest.raises(InvalidSubscription):
            send_one(client, "https://evil.example/x", p256dh, auth, {"t": 1}, _vapid(), NOW)
        with pytest.raises(InvalidSubscription):
            send_one(client, ENDPOINT, urlsafe_encode(b"\x04" + b"\x01" * 64), auth, {"t": 1}, _vapid(), NOW)
        assert not route.called
