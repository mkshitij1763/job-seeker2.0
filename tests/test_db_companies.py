from datetime import UTC, datetime, timedelta

from jobseeker.db.companies import (
    active_companies, bump_jobs_seen, get_company, list_companies, mark_inactive, needs_check, record_company,
)
from jobseeker.db.core import connect

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def test_record_and_list_active():
    conn = connect(":memory:")
    record_company(conn, "tracxn", "Tracxn", "active", "lever", "tracxn", NOW)
    record_company(conn, "acme", "Acme", "none", now=NOW)
    [(norm, company)] = active_companies(conn)
    assert norm == "tracxn" and (company.name, company.ats, company.slug) == ("Tracxn", "lever", "tracxn")
    assert [r["name_norm"] for r in list_companies(conn)] == ["tracxn", "acme"]


def test_needs_check_rules():
    conn = connect(":memory:")
    assert needs_check(conn, "new co", NOW)
    record_company(conn, "a", "A", "active", "lever", "a", NOW)
    record_company(conn, "n", "N", "none", now=NOW)
    assert not needs_check(conn, "a", NOW + timedelta(days=90))
    assert not needs_check(conn, "n", NOW + timedelta(days=29))
    assert needs_check(conn, "n", NOW + timedelta(days=30))


def test_mark_inactive_and_recheck():
    conn = connect(":memory:")
    record_company(conn, "a", "A", "active", "lever", "a", NOW)
    mark_inactive(conn, "a", NOW)
    assert get_company(conn, "a")["status"] == "inactive" and active_companies(conn) == []
    assert needs_check(conn, "a", NOW + timedelta(days=31))


def test_bump_jobs_seen_only_for_known():
    conn = connect(":memory:")
    record_company(conn, "a", "A", "active", "lever", "a", NOW)
    bump_jobs_seen(conn, "a")
    bump_jobs_seen(conn, "a")
    bump_jobs_seen(conn, "unknown")
    assert get_company(conn, "a")["jobs_seen"] == 2


def test_rerecord_updates_status():
    conn = connect(":memory:")
    record_company(conn, "a", "A", "none", now=NOW)
    record_company(conn, "a", "A Ltd", "active", "ashby", "a", NOW + timedelta(days=31))
    row = get_company(conn, "a")
    assert (row["status"], row["ats"], row["display_name"]) == ("active", "ashby", "A Ltd")
