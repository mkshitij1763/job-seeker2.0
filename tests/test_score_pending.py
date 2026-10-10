from datetime import UTC, datetime

from jobseeker.config import UserPrefs
from jobseeker.db import queries
from jobseeker.db.core import connect
from jobseeker.db.jobs import set_verdict, upsert_job
from tests.factories import make_job

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)


def _pending_job(conn, uid, n=1, prescore=50, prefix="q"):
    ids = []
    for i in range(n):
        j, _ = upsert_job(conn, make_job(source_job_id=f"{prefix}{i}", fingerprint=f"{prefix}{i}",
                                         title=f"Product Analyst {prefix}{i}"), NOW)
        set_verdict(conn, uid, j, None, prescore + i, "h", NOW)
        ids.append(j)
    conn.commit()
    return ids


def _new_user(conn, uid=3):
    conn.execute("INSERT INTO users (id, email, name, created_at) VALUES (?, 'new@example.com', 'New', 't')", (uid,))
    conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at, updated_at)
                    VALUES (?, ?, 1, NULL, 't', 't')""",
                 (uid, UserPrefs(roles=["Product Analyst"], cities=["Pune"]).model_dump_json()))
    conn.commit()


def test_pending_lists_unscored_visible_matches_by_prescore(settings):
    conn = connect(settings.db_path)
    _new_user(conn)
    low, high = _pending_job(conn, 3, 2)
    hidden, _ = upsert_job(conn, make_job(source_job_id="h", fingerprint="h", title="Sales"), NOW)
    set_verdict(conn, 3, hidden, "title: sales", 99, "h", NOW)
    conn.commit()
    p = queries.pending_scores(conn, 3)
    assert p["count"] == 2 and [r["job_id"] for r in p["rows"]] == [high, low]
    assert not queries.has_any_score(conn, 3)


def test_scored_jobs_are_not_pending(seeded_two, settings):
    conn = connect(settings.db_path)
    set_verdict(conn, 2, seeded_two["j1"], None, 50, "h", NOW)  # user 2 has a score for J1
    conn.commit()
    assert queries.pending_scores(conn, 2)["count"] == 0 and queries.has_any_score(conn, 2)


def test_review_band_shows_score_pending(seeded_two, client_as, settings):
    _pending_job(connect(settings.db_path), 2)
    page = client_as(2).get("/?band=review").text
    assert "Score pending" in page and "1 match is waiting for a score" in page


def test_apply_band_with_jobs_does_not_show_pending(seeded_two, client_as, settings):
    _pending_job(connect(settings.db_path), 2)
    assert "Score pending" not in client_as(2).get("/?band=apply").text


def test_empty_list_with_pending_matches_says_so(client_as, settings):
    conn = connect(settings.db_path)
    _new_user(conn)
    _pending_job(conn, 3, 3)
    page = client_as(3).get("/").text
    assert "3 matches are waiting for a score" in page and "No scored jobs here yet." in page


def test_today_first_run_is_not_all_caught_up(client_as, settings):
    conn = connect(settings.db_path)
    _new_user(conn)
    _pending_job(conn, 3, 3)
    page = client_as(3).get("/today").text
    assert "All caught up" not in page and "Your first matches are on the way" in page
    assert "3 jobs match your filters" in page


def test_today_after_scores_keeps_all_caught_up(seeded_two, client_as):
    assert "All caught up" in client_as(2).get("/today").text or "Shortlisted" in client_as(2).get("/today").text
