from datetime import UTC, datetime

from jobseeker.db import queries
from jobseeker.db.applications import blocked_companies
from jobseeker.db.core import connect
from jobseeker.db.jobs import latest_score
from jobseeker.db.runs import last_run, start_run
from jobseeker.web.view import nav_counts

NOW = datetime.now(UTC)


def test_inbox_and_facets_are_per_user(settings, seeded_two):
    conn = connect(settings.db_path)
    owner_ids = {r["app_id"] for r in queries.inbox(conn, 1, band="all")}
    assert seeded_two["roommate_app"] not in owner_ids
    assert {r["app_id"] for r in queries.inbox(conn, 2, band="all")} == {seeded_two["roommate_app"]}
    assert "growth_analyst" not in queries.inbox_facets(conn, 1)["families"]


def test_latest_score_and_detail_are_per_user(settings, seeded_two):
    conn = connect(settings.db_path)
    assert latest_score(conn, 1, seeded_two["j1"])["score"] == 88
    assert latest_score(conn, 2, seeded_two["j1"])["score"] == 91
    assert queries.application_detail(conn, 2, seeded_two["owner_apps"][0]) is None


def test_boards_counts_and_stats_are_per_user(settings, seeded_two):
    conn = connect(settings.db_path)
    assert all(c["app_id"] != seeded_two["roommate_app"]
               for cards in queries.pipeline(conn, 1, NOW).values() for c in cards)
    assert [c["app_id"] for c in queries.pipeline(conn, 2, NOW)["shortlisted"]] == [seeded_two["roommate_app"]]
    assert nav_counts(conn, 2)["jobs"] == 1
    t = queries.today(conn, 2, NOW)
    assert all(r["app_id"] == seeded_two["roommate_app"] for k in ("send", "ready", "find_contacts") for r in t[k])
    assert queries.stats(conn, 2, NOW)["drafted"] == 0


def test_blocklist_is_per_user(settings, seeded_two):
    conn = connect(settings.db_path)
    assert "cred" in blocked_companies(conn, 2)
    assert "cred" not in blocked_companies(conn, 1)


def test_last_run_shows_own_and_shared_runs(settings, seeded_two):
    conn = connect(settings.db_path)
    start_run(conn, NOW, user_id=2)
    shared = start_run(conn, NOW, user_id=None, kind="fetch")
    assert last_run(conn, 1)["id"] == shared
    mine = start_run(conn, NOW, user_id=1)
    assert last_run(conn, 1)["id"] == mine
