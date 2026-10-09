from datetime import UTC, datetime, timedelta

from jobseeker.db.core import connect
from jobseeker.db.jobs import get_user_job, upsert_job
from jobseeker.pipeline.evaluate import evaluate
from tests.factories import make_job

NOW = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)


def _db(tmp_path):
    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'roomie@example.com', 't')")
    conn.commit()
    return conn


def test_new_jobs_get_verdicts_per_user(tmp_path, prefs, facts):
    conn = _db(tmp_path)
    ok, _ = upsert_job(conn, make_job(source_job_id="ok", fingerprint="f1", posted_at=NOW), NOW)
    sde, _ = upsert_job(conn, make_job(source_job_id="sde", fingerprint="f2", title="Software Engineer", posted_at=NOW), NOW)
    stats = evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 0}), facts, NOW)
    assert stats.evaluated == 2 and stats.filtered == 1
    assert get_user_job(conn, 1, ok)["filter_reason"] is None and get_user_job(conn, 1, ok)["prescore"] is not None
    assert get_user_job(conn, 1, sde)["filter_reason"]
    assert get_user_job(conn, 2, ok) is None  # other users untouched
    assert evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 0}), facts, NOW).evaluated == 0  # nothing new


def test_low_prescore_cutoff_only_for_new_jobs(tmp_path, prefs, facts):
    conn = _db(tmp_path)
    j, _ = upsert_job(conn, make_job(source_job_id="a", fingerprint="fa", posted_at=NOW, jd_text="x"), NOW)
    evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 999}), facts, NOW)
    assert get_user_job(conn, 1, j)["filter_reason"].startswith("low pre-score: ")
    conn.execute("UPDATE jobs SET jd_text = 'SQL A/B testing 2-4 years', jd_hash = 'changed' WHERE id = ?", (j,))
    conn.commit()
    assert evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 999}), facts, NOW).evaluated == 1
    assert get_user_job(conn, 1, j)["filter_reason"] is None  # a changed description re-judges without the cutoff


def test_old_jobs_are_not_evaluated(tmp_path, prefs, facts):
    conn = _db(tmp_path)
    upsert_job(conn, make_job(source_job_id="old", fingerprint="fo", posted_at=NOW - timedelta(days=30)),
               NOW - timedelta(days=30))
    assert evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 0}), facts, NOW).evaluated == 0


def test_late_joiner_gets_verdicts_for_existing_jobs(tmp_path, prefs, facts):
    conn = _db(tmp_path)
    j, _ = upsert_job(conn, make_job(source_job_id="ok", fingerprint="f1", posted_at=NOW), NOW)
    evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 0}), facts, NOW)
    evaluate(conn, 2, prefs.model_copy(update={'min_prescore': 0}), facts, NOW)
    assert get_user_job(conn, 2, j) is not None
