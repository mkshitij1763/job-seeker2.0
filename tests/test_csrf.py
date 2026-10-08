import pytest


@pytest.fixture
def web(client_as, seeded):
    c = client_as(1, follow_redirects=False)
    c.headers.pop("Origin")
    return c, seeded[0]


def test_foreign_origin_blocked(web):
    c, a = web
    r = c.post(f"/applications/{a}/notes", data={"notes": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.text == "Request blocked"


def test_missing_both_headers_blocked(web):
    c, a = web
    assert c.post(f"/applications/{a}/notes", data={"notes": "x"}).status_code == 403


def test_same_origin_fetch_metadata_allowed(web):
    c, a = web
    assert c.post(f"/applications/{a}/notes", data={"notes": "x"}, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 303


def test_cross_site_fetch_metadata_blocked_even_with_origin(web):
    c, a = web
    r = c.post(f"/applications/{a}/notes", data={"notes": "x"},
               headers={"Origin": "https://testserver", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_get_never_blocked(web):
    c, a = web
    assert c.get(f"/applications/{a}", headers={"Origin": "https://evil.example"}).status_code == 200
