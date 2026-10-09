import sqlite3
from datetime import UTC, datetime

from jobseeker.config import ContactsConfig, Settings
from jobseeker.db.core import SCHEMA_V0, connect
from jobseeker.db.jobs import upsert_job
from jobseeker.db.usage import Budget, contacts_limits
from tests.factories import make_job

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_contacts_config_defaults(prefs):
    c = prefs.contacts
    assert (c.tavily_monthly_limit, c.apify_monthly_usd_limit, c.hunter_monthly_limit) == (950, 4.5, 45)
    assert (c.smtp_daily_limit, c.smtp_pause_seconds) == (60, 2.0)


def test_settings_read_contact_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("TAVILY_API_KEY", "tv")
    monkeypatch.setenv("APIFY_API_TOKEN", "ap")
    monkeypatch.setenv("HUNTER_API_KEY", "hu")
    s = Settings(jobseeker_home=tmp_path)
    assert (s.tavily_api_key, s.apify_api_token, s.hunter_api_key) == ("tv", "ap", "hu")


def test_fresh_db_has_contact_tables(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    for table in ("application_contacts", "contact_candidates", "company_domains", "usage"):
        assert _columns(conn, table), table
    assert {"find_status", "find_error", "find_started_at"} <= _columns(conn, "applications")


def test_migrates_older_db(tmp_path):
    path = tmp_path / "db.sqlite"
    raw = sqlite3.connect(path)
    raw.executescript(SCHEMA_V0)
    raw.close()
    conn = connect(path, check_version=False)
    upsert_job(conn, make_job())
    for t in ("application_contacts", "contact_candidates", "company_domains", "usage"):
        conn.execute(f"DROP TABLE {t}")
    for col in ("find_status", "find_error", "find_started_at"):
        conn.execute(f"ALTER TABLE applications DROP COLUMN {col}")
    conn.commit()
    conn.close()
    conn = connect(path, check_version=False)
    assert "rank" in _columns(conn, "application_contacts")
    assert "find_status" in _columns(conn, "applications")
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_budget_caps_and_summary():
    conn = connect(":memory:")
    b = Budget(conn, 1, contacts_limits(ContactsConfig(tavily_monthly_limit=2, smtp_daily_limit=1,
                                                 apify_monthly_usd_limit=0.15)), NOW)
    assert b.can("tavily") and b.can("tavily", 2) and not b.can("tavily", 3)
    b.spend("tavily", 2)
    assert not b.can("tavily")
    assert b.can("apify", 0.10)
    b.spend("apify", 0.10)
    assert not b.can("apify", 0.10)
    b.spend("smtp")
    assert not b.can("smtp")
    assert Budget(conn, 1, contacts_limits(ContactsConfig(smtp_daily_limit=1)), NOW.replace(day=9)).can("smtp")  # daily resets
    assert b.summary() == ("Your Tavily 2/2 · All 2/2 · Apify $0.10/$0.15 · All $0.10/$0.15 · Hunter 0/45 · All 0/45 · "
                           "SMTP today 1/1 · All 1/1")


def test_budget_share_and_global_caps(tmp_path):
    from jobseeker.db.usage import Limit
    conn = connect(tmp_path / "db.sqlite")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    limits = {"tavily": Limit("month", 3, 2)}
    a, b = Budget(conn, 1, limits, NOW), Budget(conn, 2, limits, NOW)
    a.spend("tavily")
    a.spend("tavily")
    assert not a.can("tavily")          # user 1 is at their share
    assert b.can("tavily")
    b.spend("tavily")
    assert not b.can("tavily")          # the global cap (3) is reached
