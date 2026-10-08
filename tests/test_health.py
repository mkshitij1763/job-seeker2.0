import sqlite3

from jobseeker.db.core import connect


def test_healthz_ok_without_session(anon_client):
    r = anon_client().get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert r.headers["cache-control"] == "no-store"


def test_head_same_status_no_body(anon_client):
    r = anon_client().head("/healthz")
    assert r.status_code == 200 and r.content == b""


def test_schema_mismatch_is_503(anon_client, settings):
    client = anon_client()  # create_app refuses an out-of-date DB, so the schema changes under a running app
    conn = connect(settings.db_path)
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    r = client.get("/healthz")
    assert r.status_code == 503 and r.json() == {"ok": False, "check": "schema"}


def test_healthz_missing_db_creates_nothing(tmp_path):
    from jobseeker.web.health import check

    db = tmp_path / "data" / "jobseeker.db"
    assert check(db) == (503, {"ok": False, "check": "db"})
    assert not db.exists() and not db.parent.exists()


def test_never_uses_get_conn(anon_client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("healthz must not use get_conn")
    monkeypatch.setattr("jobseeker.web.deps.get_conn", boom)
    assert anon_client().get("/healthz").status_code == 200


def test_locked_db_is_503_db(tmp_path, monkeypatch):
    from jobseeker.web import health

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(health.sqlite3, "connect", locked)
    assert health.check(tmp_path / "x.db") == (503, {"ok": False, "check": "db"})
