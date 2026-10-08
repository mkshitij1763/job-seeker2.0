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
