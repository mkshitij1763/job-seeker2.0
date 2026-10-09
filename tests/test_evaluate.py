from datetime import UTC, datetime

from typer.testing import CliRunner

from jobseeker.cli import app
from jobseeker.db.applications import ensure_application, get_status, transition
from jobseeker.db.core import connect
from jobseeker.db.jobs import get_user_job, set_filter_reason, upsert_job
from jobseeker.pipeline.evaluate import reevaluate
from tests.factories import make_job

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _db(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    pune, _ = upsert_job(conn, make_job(source_job_id="p", fingerprint="fp", location="Pune", location_city="pune",
                                        posted_at=NOW))
    blr, _ = upsert_job(conn, make_job(source_job_id="b", fingerprint="fb", posted_at=NOW))
    return conn, pune, blr


def test_loosening_restores_and_tightening_hides(tmp_path, prefs, facts):
    conn, pune, blr = _db(tmp_path)
    only_blr = prefs.model_copy(update={"cities": ["Bengaluru"], "remote_india_ok": False, "min_prescore": 0})
    reevaluate(conn, 1, only_blr, facts, NOW, apply=True)
    assert get_user_job(conn, 1, pune)["filter_reason"].startswith("location")
    both = only_blr.model_copy(update={"cities": ["Bengaluru", "Pune"]})
    report = reevaluate(conn, 1, both, facts, NOW, apply=True)
    assert [r["job_id"] for r in report.restored] == [pune]
    assert get_user_job(conn, 1, pune)["filter_reason"] is None


def test_preview_matches_apply_and_skips_only_pre_outreach(tmp_path, prefs, facts):
    conn, pune, blr = _db(tmp_path)
    base = prefs.model_copy(update={"min_prescore": 0})
    reevaluate(conn, 1, base, facts, NOW, apply=True)          # both jobs visible to start with
    a = ensure_application(conn, 1, pune, NOW)
    transition(conn, a, "shortlisted")
    tight = base.model_copy(update={"cities": ["Bengaluru"], "remote_india_ok": False})
    preview = reevaluate(conn, 1, tight, facts, NOW, apply=False)
    assert get_user_job(conn, 1, pune)["filter_reason"] is None   # a preview writes nothing
    applied = reevaluate(conn, 1, tight, facts, NOW, apply=True)
    assert [r["job_id"] for r in preview.hidden] == [r["job_id"] for r in applied.hidden] == [pune]
    assert preview.skipped_apps == applied.skipped_apps == [a] and get_status(conn, a) == "skipped"


def test_scored_job_never_hidden_by_low_prescore(tmp_path, prefs, facts):
    from jobseeker.db.jobs import save_score
    from jobseeker.models import ScoreResult
    conn, pune, blr = _db(tmp_path)
    save_score(conn, 1, blr, ScoreResult(score=80, breakdown={}, matches=[], gaps=[], recommendation="apply",
                                         role_family="pa"), "m", "v1", "h")
    strict = prefs.model_copy(update={"min_prescore": 1000})
    reevaluate(conn, 1, strict, facts, NOW, apply=True)
    assert get_user_job(conn, 1, blr)["filter_reason"] is None


def test_other_user_untouched(tmp_path, prefs, facts):
    conn, pune, blr = _db(tmp_path)
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    set_filter_reason(conn, 2, pune, "title: x")
    reevaluate(conn, 1, prefs, facts, NOW, apply=True)
    assert get_user_job(conn, 2, pune)["filter_reason"] == "title: x"


def test_5000_jobs_under_two_seconds(tmp_path, prefs, facts):
    import time
    conn = connect(tmp_path / "db.sqlite")
    for i in range(5000):
        upsert_job(conn, make_job(source_job_id=str(i), fingerprint=f"f{i}", posted_at=NOW))
    t = time.perf_counter()
    reevaluate(conn, 1, prefs, facts, NOW, apply=True)
    assert time.perf_counter() - t < 2.0


def _job(conn, n, **kw):
    job_id, _ = upsert_job(conn, make_job(source_job_id=f"r{n}", fingerprint=f"r{n}", **kw), NOW)
    return job_id


def test_ported_refilter_scenario(prefs, facts):
    conn = connect(":memory:")
    p = prefs.model_copy(update={"min_prescore": 0})
    ok = _job(conn, 1, jd_text="1-2 years of experience.")
    senior = _job(conn, 2, jd_text="Needs 4+ years of experience.")
    approved = _job(conn, 3, jd_text="Needs 6+ years of experience.")
    old = _job(conn, 4, jd_text="Fine.", posted_at=datetime(2025, 1, 1, tzinfo=UTC))
    a_senior = ensure_application(conn, 1, senior, NOW)
    transition(conn, a_senior, "drafted", now=NOW)
    a_approved = ensure_application(conn, 1, approved, NOW)
    transition(conn, a_approved, "drafted", now=NOW)
    transition(conn, a_approved, "approved", now=NOW)

    preview = reevaluate(conn, 1, p, facts, NOW, apply=False)
    assert preview.skipped_apps == [a_senior] and preview.kept_apps == [a_approved]
    assert get_user_job(conn, 1, senior) is None  # a dry run writes nothing

    reevaluate(conn, 1, p, facts, NOW, apply=True)
    assert get_user_job(conn, 1, senior)["filter_reason"] == "experience: 4+ years"
    assert get_status(conn, a_senior) == "skipped"
    assert get_user_job(conn, 1, approved)["filter_reason"] == "experience: 6+ years"
    assert get_status(conn, a_approved) == "approved"  # a Gmail draft exists: never touched
    assert get_user_job(conn, 1, ok)["filter_reason"] is None
    assert get_user_job(conn, 1, old) is None  # past max_age_days: not re-judged
    again = reevaluate(conn, 1, p, facts, NOW, apply=True)
    assert not (again.hidden or again.restored or again.new or again.skipped_apps)  # idempotent


def test_refilter_command_is_a_dry_run_unless_applied(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    conn = connect(settings.db_path)
    job = _job(conn, 9, jd_text="Needs 7+ years of experience.", posted_at=datetime.now(UTC))
    set_filter_reason(conn, 1, job, None)
    conn.close()
    out = CliRunner().invoke(app, ["refilter"]).output
    assert "experience: 7+ years" in out and "--apply" in out
    assert get_user_job(connect(settings.db_path), 1, job)["filter_reason"] is None
    CliRunner().invoke(app, ["refilter", "--apply"])
    assert get_user_job(connect(settings.db_path), 1, job)["filter_reason"] == "experience: 7+ years"
