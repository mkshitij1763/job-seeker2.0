import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from jobseeker.b64 import urlsafe_encode
from jobseeker.db.core import connect


@pytest.fixture(autouse=True)
def _fresh_rate_limit(monkeypatch):
    monkeypatch.setattr("jobseeker.web.push._last_test", {})


def _sub(endpoint="https://web.push.apple.com/dev1"):
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": endpoint, "keys": {"p256dh": urlsafe_encode(pub), "auth": urlsafe_encode(os.urandom(16))}}


def _rows(settings):
    return [tuple(r) for r in connect(settings.db_path).execute(
        "SELECT user_id, endpoint FROM push_subscriptions ORDER BY id")]


def test_sw_js_is_public_at_root_with_no_cache(anon_client):
    r = anon_client().get("/sw.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    assert r.headers["content-type"].startswith("text/javascript")
    assert "showNotification" in r.text and "notificationclick" in r.text and "fetch" not in r.text


def test_subscribe_requires_session_and_origin(anon_client, client_as):
    assert anon_client().post("/push/subscribe", json=_sub()).status_code in (303, 401)
    c = client_as(1)
    assert c.post("/push/subscribe", json=_sub(), headers={"Origin": "https://evil.example"}).status_code == 403


def test_subscribe_upserts_and_validates(client_as, settings):
    c = client_as(1)
    assert c.post("/push/subscribe", json=_sub()).status_code == 204
    assert c.post("/push/subscribe", json=_sub()).status_code == 204
    assert _rows(settings) == [(1, "https://web.push.apple.com/dev1")]
    bad = _sub()
    bad["keys"]["p256dh"] = "short"
    assert c.post("/push/subscribe", json=bad).status_code == 422
    assert c.post("/push/subscribe", json={**_sub(), "endpoint": "http://plain"}).status_code == 422
    assert c.post("/push/subscribe", json={**_sub(), "endpoint": "https://x/" + "a" * 1100}).status_code == 422


def test_subscribe_moves_shared_device_to_new_user(client_as, settings, seeded_two):  # seeded_two adds user 2
    client_as(1).post("/push/subscribe", json=_sub())
    client_as(2).post("/push/subscribe", json=_sub())
    assert _rows(settings) == [(2, "https://web.push.apple.com/dev1")]


def test_unsubscribe_only_own(client_as, settings, seeded_two):  # seeded_two adds user 2
    client_as(1).post("/push/subscribe", json=_sub())
    assert client_as(2).post("/push/unsubscribe", json={"endpoint": _sub()["endpoint"]}).status_code == 204
    assert len(_rows(settings)) == 1
    client_as(1).post("/push/unsubscribe", json={"endpoint": _sub()["endpoint"]})
    assert _rows(settings) == []


def test_push_test_unconfigured_and_rate_limited(client_as, monkeypatch, settings):
    c = client_as(1)
    c.post("/push/subscribe", json=_sub())
    r = c.post("/push/test", json={"endpoint": _sub()["endpoint"]})
    assert r.status_code == 409 and "aren't set up" in r.text
    monkeypatch.setattr("jobseeker.web.push._keys", lambda request: object())
    monkeypatch.setattr("jobseeker.web.push.send_one", lambda *a: 201)
    assert c.post("/push/test", json={"endpoint": _sub()["endpoint"]}).status_code == 200
    assert c.post("/push/test", json={"endpoint": _sub()["endpoint"]}).status_code == 429
