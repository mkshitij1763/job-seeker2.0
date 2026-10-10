from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.db.users import user_by_id
from tests.fakes import FakeLLM
from tests.test_run import DRAFT, SCORE, StaticSource, handler, raw

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)

GOLDEN_JOBS = [raw(source_job_id=str(i), title=t, apply_url=f"https://jobs.lever.co/cred/{i}")
               for i, t in enumerate(["Senior Product Analyst", "Product Analyst", "Software Engineer",
                                      "Growth Analyst", "Data Scientist"])]


def owner_outcome(conn):
    verdicts = [tuple(r) for r in conn.execute(
        "SELECT j.source_job_id, uj.filter_reason IS NULL FROM user_jobs uj JOIN jobs j ON j.id = uj.job_id "
        "WHERE uj.user_id = 1 ORDER BY j.source_job_id")]
    shortlist = [r[0] for r in conn.execute(
        "SELECT j.source_job_id FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.user_id = 1 "
        "AND a.status IN ('shortlisted', 'drafted') ORDER BY j.source_job_id")]
    scored = [r[0] for r in conn.execute(
        "SELECT j.source_job_id FROM scores s JOIN jobs j ON j.id = s.job_id WHERE s.user_id = 1 ORDER BY s.id")]
    return verdicts, shortlist, scored


# Frozen from run_daily on GOLDEN_JOBS (owner prefs, rubric, facts) before run_all existed.
GOLDEN = ([('0', 1), ('1', 1), ('2', 0), ('3', 1), ('4', 0)], ['0', '1', '3'], ['1', '0', '3'])


def _cfg(prefs):
    """The fixture AppConfig equivalent of the owner's prefs (spec 3's app.example.yaml has the same values)."""
    from jobseeker.config import REPO_ROOT, load_app_config
    return load_app_config(REPO_ROOT / "config" / "app.example.yaml")


def _run(conn, prefs, rubric, facts, *, users, trigger="cli", notify=None, sources=GOLDEN_JOBS, llm=None):
    from jobseeker.pipeline.run import run_all
    calls = []
    report = run_all(conn, users=users, trigger=trigger, fetch=True, plan_cap=60, client=None,
                     llm=llm or FakeLLM(handler=handler), cfg=_cfg(prefs), rubric=rubric, now=NOW,
                     describe=lambda s, i: "",
                     sources_factory=lambda *a, **k: [StaticSource("lever:cred", list(sources))],
                     context=lambda conn, uid: (prefs, facts),
                     notify=notify or (lambda c, uid, started, now: calls.append((uid, started, c.in_transaction)) or None))
    return report, calls


def test_golden_owner_alone_matches_run_daily(tmp_path, prefs, rubric, facts):
    conn = connect(tmp_path / "db")
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)])
    assert report.aborted is None
    assert owner_outcome(conn) == GOLDEN


def test_runs_rows_link_user_to_fetch(tmp_path, prefs, rubric, facts):
    conn = connect(tmp_path / "db")
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="schedule")
    fetch = conn.execute("SELECT * FROM runs WHERE kind = 'fetch'").fetchone()
    user = conn.execute("SELECT * FROM runs WHERE kind = 'user'").fetchone()
    assert fetch["trigger"] == "schedule" and fetch["user_id"] is None and fetch["finished_at"]
    assert user["parent_id"] == fetch["id"] and user["user_id"] == 1 and user["finished_at"]


def test_notify_called_after_scoring_outside_transactions(tmp_path, prefs, rubric, facts):
    conn = connect(tmp_path / "db")
    _, calls = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="schedule")
    assert len(calls) == 1 and calls[0][0] == 1 and calls[0][2] is False
    _, calls = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="cli")
    assert calls == []


def test_notify_failure_becomes_a_note(tmp_path, prefs, rubric, facts):
    conn = connect(tmp_path / "db")
    def boom(*a):
        raise RuntimeError("x")
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="schedule", notify=boom)
    assert "Couldn't send the match alert" in report.users[1].errors and report.aborted is None
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="schedule",
                     notify=lambda *a: "Couldn't send the match alert")
    assert report.users[1].errors.count("Couldn't send the match alert") == 1


def test_user_without_facts_is_skipped(tmp_path, prefs, rubric, facts):
    from jobseeker.pipeline.run import run_all
    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'roomie@example.com', 't')")
    conn.commit()
    report = run_all(conn, users=[user_by_id(conn, 1), user_by_id(conn, 2)], trigger="cli", fetch=True, plan_cap=60,
                     client=None, llm=FakeLLM(handler=handler), cfg=_cfg(prefs), rubric=rubric, now=NOW,
                     describe=lambda s, i: "", sources_factory=lambda *a, **k: [StaticSource("lever:cred", GOLDEN_JOBS)],
                     context=lambda conn, uid: (prefs, facts if uid == 1 else None), notify=lambda *a: None)
    assert report.aborted is None and report.users[1].scored > 0
    assert report.users[2].errors == ["No resume facts yet, so nothing was scored"]


def test_crash_closes_every_run_row(tmp_path, prefs, rubric, facts, monkeypatch):
    conn = connect(tmp_path / "db")
    monkeypatch.setattr("jobseeker.pipeline.run.score_round_robin", lambda *a, **k: 1 / 0)
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)])
    assert report.aborted.startswith("run aborted: ZeroDivisionError")
    assert conn.execute("SELECT COUNT(*) FROM runs WHERE finished_at IS NULL").fetchone()[0] == 0


def test_requested_runs_push_when_done_and_the_daily_run_alerts(tmp_path, prefs, rubric, facts):
    from jobseeker.pipeline.run import run_all
    conn = connect(tmp_path / "db")
    for trigger in ("fetch_now", "onboarding", "schedule", "cli"):
        daily, done = [], []
        run_all(conn, users=[user_by_id(conn, 1)], trigger=trigger, fetch=False, plan_cap=60, client=None,
                llm=FakeLLM(handler=handler), cfg=_cfg(prefs), rubric=rubric, now=NOW, describe=lambda s, i: "",
                context=lambda c, uid: (prefs, facts),
                notify=lambda c, uid, started, now: daily.append(uid),
                notify_done=lambda c, uid, started, now, stats: done.append((uid, stats.stopped_by != "")))
        assert (daily, [d[0] for d in done]) == {"fetch_now": ([], [1]), "onboarding": ([], [1]),
                                                 "schedule": ([1], []), "cli": ([], [])}[trigger], trigger
