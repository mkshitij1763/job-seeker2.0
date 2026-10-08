import sqlite3
from datetime import UTC, datetime

import pytest

from jobseeker.db import migrations as m
from jobseeker.db.core import SCHEMA_V0, connect

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def v0_db(path):
    raw = sqlite3.connect(path)
    raw.executescript(SCHEMA_V0)
    raw.commit()
    raw.close()
    return path


def _ctx(tmp_path):
    return m.MigrationContext(owner_email="owner@example.com", now=NOW, home=tmp_path)


def _add_flag(conn, ctx):
    conn.execute("CREATE TABLE flag (x INTEGER)")


def test_latest_of_empty_is_zero():
    assert m.latest([]) == 0


def test_migrate_applies_pending_in_order_and_sets_version(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")
    report = m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "flag", _add_flag)])
    raw = sqlite3.connect(db)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert raw.execute("SELECT name FROM sqlite_master WHERE name = 'flag'").fetchone()
    assert any("v1" in line for line in report)
    assert list((tmp_path / "bk").glob("pre-migrate-v0-*.db"))


def test_migrate_twice_is_a_noop(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")
    ms = [m.Migration(1, "flag", _add_flag)]
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=ms)
    assert m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=ms) == ["Already at v1"]


def test_failed_foreign_key_check_rolls_back(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")

    def orphan(conn, ctx):
        conn.execute("INSERT INTO drafts (application_id, kind, body, created_at) VALUES (999, 'email', 'x', 'now')")

    with pytest.raises(m.MigrationError):
        m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "orphan", orphan)])
    raw = sqlite3.connect(db)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
    assert raw.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


def test_dry_run_leaves_file_identical(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")
    before = db.read_bytes()
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "flag", _add_flag)], dry_run=True)
    assert db.read_bytes() == before


def test_busy_database_is_refused(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")
    holder = sqlite3.connect(db)
    holder.execute("BEGIN IMMEDIATE")
    with pytest.raises(m.DatabaseBusy):
        m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "flag", _add_flag)],
                  busy_timeout=0.1)
    holder.rollback()


def test_connect_on_old_version_raises_when_behind(tmp_path, monkeypatch):
    db = v0_db(tmp_path / "db.sqlite")
    monkeypatch.setattr(m, "MIGRATIONS", [m.Migration(1, "flag", _add_flag)])
    with pytest.raises(m.SchemaOutOfDate, match="jobseeker migrate"):
        connect(db)
    connect(db, check_version=False).close()  # migrate itself opens without the check


def test_fresh_file_lands_at_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MIGRATIONS", [m.Migration(1, "flag", _add_flag)])
    conn = connect(tmp_path / "fresh.sqlite")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def live_like_v0(path):
    """v0 DB shaped like the live one: NEW_COLUMNS appended out of order, with data."""
    from jobseeker.db.core import NEW_COLUMNS
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    find_cols = "  find_status TEXT NOT NULL DEFAULT 'idle',\n  find_error TEXT NOT NULL DEFAULT '',\n  find_started_at TEXT,\n"
    assert find_cols in SCHEMA_V0
    raw.executescript(SCHEMA_V0.replace(find_cols, ""))
    for col, ddl in NEW_COLUMNS["applications"].items():
        raw.execute(f"ALTER TABLE applications ADD COLUMN {col} {ddl}")
    raw.execute("INSERT INTO jobs (id, source, source_job_id, company, title, jd_hash, apply_url, fingerprint, "
                "first_seen_at, filter_reason, prescore) VALUES (1,'lever','a','CRED','PA','h1','u','f1','t',NULL,70),"
                "(2,'lever','b','CRED','SDE','h2','u','f2','t','title: sde',NULL)")
    raw.execute("INSERT INTO applications (id, job_id, status, created_at, updated_at) VALUES (7, 1, 'drafted', 't', 't')")
    raw.execute("INSERT INTO drafts (application_id, kind, body, created_at) VALUES (7, 'email', 'b', 't')")
    raw.execute("INSERT INTO events (application_id, at, type) VALUES (7, 't', 'status')")
    raw.execute("INSERT INTO scores (id, job_id, score, breakdown, matches, gaps, recommendation, role_family, model, "
                "rubric_version, jd_hash, created_at) VALUES (3, 1, 88, '{}', '[]', '[]', 'apply', 'pa', 'm', 'v1', 'h1', 't')")
    raw.execute("INSERT INTO usage (period, service, amount) VALUES ('2026-10', 'tavily', 5)")
    raw.execute("INSERT INTO runs (started_at) VALUES ('t')")
    raw.commit()
    raw.close()
    return path


def test_v1_preserves_ids_and_assigns_owner(tmp_path):
    db = live_like_v0(tmp_path / "db.sqlite")
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "users", m.migrate_v1)])
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    assert dict(c.execute("SELECT id, email, is_admin FROM users").fetchone()) == {
        "id": 1, "email": "owner@example.com", "is_admin": 1}
    assert tuple(c.execute("SELECT id, user_id, job_id, find_status FROM applications").fetchone()) == (7, 1, 1, "idle")
    assert c.execute("SELECT application_id FROM drafts").fetchone()[0] == 7
    assert c.execute("SELECT user_id FROM scores WHERE id = 3").fetchone()[0] == 1
    assert tuple(c.execute("SELECT user_id, period, service, amount FROM usage").fetchone()) == (1, "2026-10", "tavily", 5)
    assert tuple(c.execute("SELECT user_id, kind FROM runs").fetchone()) == (1, "legacy")
    uj = {r["job_id"]: dict(r) for r in c.execute("SELECT * FROM user_jobs")}
    assert uj[1]["prescore"] == 70 and uj[1]["jd_hash"] == "h1" and uj[2]["filter_reason"] == "title: sde"
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v1_constraints(tmp_path):
    db = live_like_v0(tmp_path / "db.sqlite")
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "users", m.migrate_v1)])
    c = sqlite3.connect(db)
    c.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    c.execute("INSERT INTO applications (user_id, job_id, created_at, updated_at) VALUES (2, 1, 't', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO applications (user_id, job_id, created_at, updated_at) VALUES (1, 1, 't', 't')")
    for sql in ("INSERT INTO applications (job_id, created_at, updated_at) VALUES (2, 't', 't')",
                "INSERT INTO blocklist (company, at) VALUES ('x', 't')",
                "INSERT INTO usage (period, service, amount) VALUES ('d', 's', 1)"):
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(sql)


def test_v1_requires_owner_email(tmp_path):
    db = live_like_v0(tmp_path / "db.sqlite")
    ctx = m.MigrationContext(owner_email="", now=NOW, home=tmp_path)
    with pytest.raises(m.MigrationError, match="OWNER_EMAIL"):
        m.migrate(db, ctx, tmp_path / "bk", migrations=[m.Migration(1, "users", m.migrate_v1)])
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == 0
