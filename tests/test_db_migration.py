import sqlite3

from jobseeker.db.core import SCHEMA_V0, connect
from jobseeker.db.jobs import upsert_job
from tests.factories import make_job


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_database_has_new_schema(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    assert "prescore" in _columns(conn, "jobs")
    assert "jobs_seen" in _columns(conn, "discovered_companies")


def test_migrates_mvp_database(tmp_path):
    path = tmp_path / "db.sqlite"
    raw = sqlite3.connect(path)
    raw.executescript(SCHEMA_V0)
    raw.close()
    conn = connect(path, check_version=False)
    job_id, _ = upsert_job(conn, make_job())
    # Turn it back into an MVP-era database.
    conn.execute("ALTER TABLE jobs DROP COLUMN prescore")
    conn.execute("DROP TABLE discovered_companies")
    conn.commit()
    conn.close()

    conn = connect(path, check_version=False)
    assert "prescore" in _columns(conn, "jobs")
    assert "status" in _columns(conn, "discovered_companies")
    assert conn.execute("SELECT title FROM jobs WHERE id = ?", (job_id,)).fetchone()[0] == "Senior Product Analyst"


def test_reconnect_does_not_alter_again(tmp_path):
    path = tmp_path / "db.sqlite"
    connect(path).close()
    connect(path).close()
    raw = sqlite3.connect(path)
    assert [r[1] for r in raw.execute("PRAGMA table_info(jobs)")].count("prescore") == 1


def test_migration_adds_jd_attempts(tmp_path):
    path = tmp_path / "db.sqlite"
    raw = sqlite3.connect(path)
    raw.executescript(SCHEMA_V0)
    raw.close()
    conn = connect(path, check_version=False)
    conn.execute("ALTER TABLE jobs DROP COLUMN jd_attempts") if "jd_attempts" in _columns(conn, "jobs") else None
    conn.commit()
    conn.close()
    conn = connect(path, check_version=False)
    assert "jd_attempts" in _columns(conn, "jobs")


def test_migration_adds_catch_all_at(tmp_path):
    path = tmp_path / "db.sqlite"
    raw = sqlite3.connect(path)
    raw.executescript(SCHEMA_V0)
    raw.close()
    conn = connect(path, check_version=False)
    conn.execute("ALTER TABLE company_domains DROP COLUMN catch_all_at") if "catch_all_at" in _columns(
        conn, "company_domains") else None
    conn.commit()
    conn.close()
    assert "catch_all_at" in _columns(connect(path, check_version=False), "company_domains")
