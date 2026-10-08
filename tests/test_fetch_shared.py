from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.pipeline.fetch import FetchStats, fetch_shared
from tests.test_run import StaticSource, raw  # reuse today's source fakes

NOW = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)


def test_writes_jobs_only(tmp_path):
    conn = connect(tmp_path / "db")
    beats = []
    stats = fetch_shared(conn, [StaticSource("lever:cred", [raw(), raw(source_job_id="2", title="SDE II")])], None, NOW,
                         set(), FetchStats(), heartbeat=lambda: beats.append(1))
    assert (stats.fetched, stats.new) == (2, 2) and beats == [1]
    for table in ("user_jobs", "scores", "applications"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_one_failing_source_is_recorded(tmp_path):
    conn = connect(tmp_path / "db")
    stats = fetch_shared(conn, [StaticSource("lever:x", error=RuntimeError("boom")), StaticSource("lever:cred", [raw()])],
                         None, NOW, set(), FetchStats())
    assert stats.new == 1 and stats.errors == ["lever:x: RuntimeError: boom"]


def test_discovery_ignores_any_users_blocklist(tmp_path, monkeypatch):
    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO blocklist (user_id, company, reason, at) VALUES (1, 'cred', 'not interested', 't')")
    conn.commit()
    seen = {}
    monkeypatch.setattr("jobseeker.pipeline.fetch.discover",
                        lambda conn, client, s, known, now, generic: seen.update(known=known) or 0)
    src = StaticSource("naukri", [raw(source="naukri")])
    src.discovers = True
    fetch_shared(conn, [src], object(), NOW, set(), FetchStats())
    assert "cred" not in seen["known"]
