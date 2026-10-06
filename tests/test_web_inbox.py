from fastapi.testclient import TestClient

from jobseeker.web.app import create_app
from jobseeker.web.filters import age, highlight


def test_highlight_escapes_and_marks():
    out = str(highlight("Use <b>SQL</b> daily; sql rocks", ["SQL"]))
    assert "&lt;b&gt;" in out and out.count("<mark>") == 2


def test_age():
    assert age(None) == "?"


def test_inbox_lists_apply_band_by_default(settings, seeded):
    client = TestClient(create_app(settings))
    r = client.get("/")
    assert r.status_code == 200
    assert "Senior Product Analyst 0" in r.text and "Senior Product Analyst 1" not in r.text
    r = client.get("/?band=review")
    assert "Senior Product Analyst 1" in r.text


def test_inbox_filter_by_family_and_source(settings, seeded):
    client = TestClient(create_app(settings))
    assert "Senior Product Analyst 0" not in client.get("/?family=apm").text
    assert "Senior Product Analyst 0" in client.get("/?source=lever").text


def test_static_assets_served(settings):
    client = TestClient(create_app(settings))
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/htmx.min.js").status_code == 200
