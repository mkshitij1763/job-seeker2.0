from datetime import UTC, datetime

from typer.testing import CliRunner

from jobseeker.cli import app
from jobseeker.db.applications import ensure_application, get_status, transition
from jobseeker.db.core import connect
from jobseeker.db.jobs import get_job, upsert_job
from jobseeker.pipeline.refilter import refilter
from tests.factories import make_job

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _job(conn, n, **kw):
    job_id, _ = upsert_job(conn, make_job(source_job_id=f"r{n}", fingerprint=f"r{n}", **kw), NOW)
    return job_id


def test_refilter_applies_current_rules_to_stored_jobs(prefs):
    conn = connect(":memory:")
    ok = _job(conn, 1, jd_text="1-2 years of experience.")
    senior = _job(conn, 2, jd_text="Needs 4+ years of experience.")
    approved = _job(conn, 3, jd_text="Needs 6+ years of experience.")
    old = _job(conn, 4, jd_text="Fine.", posted_at=datetime(2025, 1, 1, tzinfo=UTC))
    a_senior = ensure_application(conn, senior, NOW)
    transition(conn, a_senior, "drafted", now=NOW)
    a_approved = ensure_application(conn, approved, NOW)
    transition(conn, a_approved, "drafted", now=NOW)
    transition(conn, a_approved, "approved", now=NOW)

    changes = refilter(conn, prefs, NOW, apply=False)
    assert {c["job_id"] for c in changes} == {senior, approved}  # age isn't re-judged
    assert get_job(conn, senior)["filter_reason"] is None  # dry run writes nothing

    refilter(conn, prefs, NOW, apply=True)
    assert get_job(conn, senior)["filter_reason"] == "experience: 4+ years"
    assert get_status(conn, a_senior) == "skipped"
    assert get_job(conn, approved)["filter_reason"] == "experience: 6+ years"
    assert get_status(conn, a_approved) == "approved"  # a Gmail draft exists: never touched
    assert get_job(conn, ok)["filter_reason"] is None and get_job(conn, old)["filter_reason"] is None
    assert refilter(conn, prefs, NOW, apply=True) == []  # idempotent


def test_refilter_command_is_a_dry_run_unless_applied(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    conn = connect(settings.db_path)
    job = _job(conn, 9, jd_text="Needs 7+ years of experience.")
    conn.close()
    out = CliRunner().invoke(app, ["refilter"]).output
    assert "experience: 7+ years" in out and "--apply" in out
    assert get_job(connect(settings.db_path), job)["filter_reason"] is None
    CliRunner().invoke(app, ["refilter", "--apply"])
    assert get_job(connect(settings.db_path), job)["filter_reason"] == "experience: 7+ years"
