import json
import sqlite3
import threading

from jobseeker.db.core import connect
from jobseeker.db.jobs import (
    get_job, job_from_row, jobs_needing_score, latest_score, save_score,
    set_filter_reason, upsert_job,
)
from jobseeker.models import ScoreResult, jd_hash
from tests.factories import make_job


def _conn():
    return connect(":memory:")


def test_upsert_new_then_exact_repeat():
    conn = _conn()
    job_id, is_new = upsert_job(conn, make_job())
    assert is_new
    again_id, again_new = upsert_job(conn, make_job(title="Senior Product Analyst II"))
    assert (again_id, again_new) == (job_id, False)
    assert get_job(conn, job_id)["title"] == "Senior Product Analyst II"


def test_upsert_cross_source_duplicate():
    conn = _conn()
    first_id, _ = upsert_job(conn, make_job(jd_text="short"))
    dup = make_job(source="greenhouse", source_job_id="gh-9", apply_url="https://x.example/9",
                   jd_text="a much longer job description text")
    dup_id, is_new = upsert_job(conn, dup)
    assert (dup_id, is_new) == (first_id, False)
    row = get_job(conn, first_id)
    assert row["jd_text"] == "a much longer job description text"
    assert row["jd_hash"] == jd_hash("a much longer job description text")
    assert json.loads(row["alt_urls"]) == ["https://x.example/9"]
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_job_from_row_roundtrip():
    conn = _conn()
    job_id, _ = upsert_job(conn, make_job(remote=True, is_remote=True))
    job = job_from_row(get_job(conn, job_id))
    assert job.title == "Senior Product Analyst" and job.is_remote is True


def test_jobs_needing_score_respects_filter_hash_and_version():
    conn = _conn()
    a, _ = upsert_job(conn, make_job())
    b, _ = upsert_job(conn, make_job(source_job_id="abc-2", fingerprint="fp2"))
    set_filter_reason(conn, b, "location: Hyderabad")
    assert [r["id"] for r in jobs_needing_score(conn, "v1", 10)] == [a]
    result = ScoreResult(score=80, breakdown={"role_fit": 30}, matches=["SQL"], gaps=[],
                         recommendation="apply", role_family="senior_product_analyst")
    save_score(conn, a, result, "openai/gpt-oss-20b", "v1", get_job(conn, a)["jd_hash"])
    assert jobs_needing_score(conn, "v1", 10) == []
    assert [r["id"] for r in jobs_needing_score(conn, "v2", 10)] == [a]
    assert [r["id"] for r in jobs_needing_score(conn, "v1", 10, force=True)] == [a]
    assert latest_score(conn, a)["score"] == 80


def test_concurrent_reader_during_write(tmp_path):
    path = tmp_path / "db.sqlite"
    writer = connect(path)
    upsert_job(writer, make_job())
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("UPDATE jobs SET title='x'")
    errors: list[Exception] = []

    def read():
        try:
            reader = connect(path)
            reader.execute("SELECT COUNT(*) FROM jobs").fetchone()
            reader.close()
        except sqlite3.OperationalError as e:
            errors.append(e)

    t = threading.Thread(target=read)
    t.start()
    t.join(10)
    writer.commit()
    assert errors == []


def test_same_source_refresh_keeps_longer_cross_source_jd():
    conn = _conn()
    gh = make_job(source="greenhouse", source_job_id="gh-1", jd_text="short")
    job_id, _ = upsert_job(conn, gh)
    upsert_job(conn, make_job(source="lever", source_job_id="lv-1", apply_url="https://lv/a",
                              jd_text="a much longer job description text"))
    upsert_job(conn, gh)
    assert get_job(conn, job_id)["jd_text"] == "a much longer job description text"


def test_same_source_refresh_without_alternates_takes_new_jd():
    conn = _conn()
    job_id, _ = upsert_job(conn, make_job(jd_text="a long original description"))
    upsert_job(conn, make_job(jd_text="edited"))
    assert get_job(conn, job_id)["jd_text"] == "edited"


def test_jobs_needing_score_orders_by_prescore():
    from jobseeker.db.jobs import set_prescore

    conn = _conn()
    a, _ = upsert_job(conn, make_job(source_job_id="a", fingerprint="fa"))
    b, _ = upsert_job(conn, make_job(source_job_id="b", fingerprint="fb"))
    c, _ = upsert_job(conn, make_job(source_job_id="c", fingerprint="fc"))
    set_prescore(conn, a, 40)
    set_prescore(conn, b, 90)
    assert [r["id"] for r in jobs_needing_score(conn, "v1", -1)] == [b, a, c]


def test_set_jd_text_keeps_longer_and_rehashes():
    from jobseeker.db.jobs import set_jd_text

    conn = _conn()
    job_id, _ = upsert_job(conn, make_job(jd_text=""))
    set_jd_text(conn, job_id, "full description")
    set_jd_text(conn, job_id, "short")
    row = get_job(conn, job_id)
    assert row["jd_text"] == "full description" and row["jd_hash"] == jd_hash("full description")


def test_expire_unscored_and_missing_prescore():
    from datetime import UTC, datetime, timedelta

    from jobseeker.db.jobs import expire_unscored, jobs_missing_prescore, set_prescore

    now = datetime(2026, 10, 7, tzinfo=UTC)
    conn = _conn()
    old, _ = upsert_job(conn, make_job(source_job_id="old", fingerprint="fo", posted_at=now - timedelta(days=9)))
    fresh, _ = upsert_job(conn, make_job(source_job_id="new", fingerprint="fn", posted_at=now - timedelta(days=1)))
    scored, _ = upsert_job(conn, make_job(source_job_id="s", fingerprint="fs", posted_at=now - timedelta(days=9)))
    save_score(conn, scored, ScoreResult(score=80, breakdown={}, matches=[], gaps=[], recommendation="apply",
                                         role_family="other"), "m", "v1", "h")
    assert expire_unscored(conn, now, 7) == 1
    assert get_job(conn, old)["filter_reason"] == "stale: never scored"
    assert get_job(conn, scored)["filter_reason"] is None
    assert [r["id"] for r in jobs_missing_prescore(conn)] == [fresh]
    set_prescore(conn, fresh, 50)
    assert jobs_missing_prescore(conn) == []
