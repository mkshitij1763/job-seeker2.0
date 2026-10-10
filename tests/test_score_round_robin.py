from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.db.jobs import set_prescore, upsert_job
from jobseeker.llm import LLMQuotaExceeded, LLMUnavailable
from jobseeker.pipeline.score import Scorer, UserStats, score_round_robin
from jobseeker.scoring.scorer import LLMScore
from tests.factories import make_job
from tests.fakes import FakeLLM

NOW = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)
SCORE = dict(role_family="product_analyst", required_years=2, role_fit=30, experience_fit=25, skills_match=15, company=15,
             location_pay=7, matches=["SQL"], gaps=[])


def _setup(tmp_path, users=(1, 2, 3), jobs_per_user=12):
    conn = connect(tmp_path / "db")
    for u in users:
        if u != 1:
            conn.execute("INSERT INTO users (id, email, created_at) VALUES (?, ?, 't')", (u, f"u{u}@x"))
    for i in range(jobs_per_user):
        j, _ = upsert_job(conn, make_job(source_job_id=f"j{i}", fingerprint=f"f{i}", jd_text="SQL"), NOW)
        for u in users:
            set_prescore(conn, u, j, 100 - i)
    conn.commit()
    return conn


def _cfg(global_scores=150, per_run=80, batch=5):
    from jobseeker.config import AppConfig
    cfg = AppConfig()
    cfg.budgets.global_scores_per_day, cfg.budgets.score_per_run, cfg.budgets.score_batch = global_scores, per_run, batch
    return cfg


def _scorers(prefs, facts, users=(1, 2, 3), force=False):
    return [Scorer(u, prefs, facts, "h", UserStats(), force=force) for u in users]


def test_batches_interleave(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path)
    order = []
    llm = FakeLLM(handler=lambda schema, prompt: SCORE)
    import jobseeker.pipeline.score as score_mod
    real = score_mod.save_score
    score_mod_save = lambda conn, uid, *a, **k: order.append(uid) or real(conn, uid, *a, **k)  # noqa: E731
    score_mod.save_score = score_mod_save
    try:
        score_round_robin(conn, _scorers(prefs, facts), llm, rubric, _cfg(global_scores=30), NOW)
    finally:
        score_mod.save_score = real
    assert order[:15] == [1] * 5 + [2] * 5 + [3] * 5


def test_share_and_global_cap(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path)
    scorers = _scorers(prefs, facts)
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=30), NOW)
    assert [s.stats.scored for s in scorers] == [10, 10, 10]  # share = 30 // 3, no pooling
    assert all(s.stats.stopped_by == "share" for s in scorers)


def test_stop_reasons_are_precise(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2), jobs_per_user=3)
    scorers = _scorers(prefs, facts, users=(1, 2))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(per_run=2), NOW)
    assert [s.stats.stopped_by for s in scorers] == ["run_cap", "run_cap"]
    scorers = _scorers(prefs, facts, users=(1, 2))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(), NOW)
    assert [s.stats.stopped_by for s in scorers] == ["no_candidates", "no_candidates"]


def test_quota_and_unavailable_stop_everyone(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path)
    def quota(schema, prompt):
        raise LLMQuotaExceeded("gone")
    scorers = _scorers(prefs, facts)
    assert score_round_robin(conn, scorers, FakeLLM(handler=quota), rubric, _cfg(), NOW) == "quota"
    assert {s.stats.stopped_by for s in scorers} == {"quota"}
    def down(schema, prompt):
        raise LLMUnavailable("down")
    assert score_round_robin(conn, _scorers(prefs, facts), FakeLLM(handler=down), rubric, _cfg(), NOW) == "unavailable"


def test_force_scores_each_job_once(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1,), jobs_per_user=4)
    llm = FakeLLM(handler=lambda s, p: SCORE)
    (s,) = _scorers(prefs, facts, users=(1,), force=True)
    score_round_robin(conn, [s], llm, rubric, _cfg(), NOW)
    assert s.stats.scored == 4 and s.stats.stopped_by == "no_candidates"


def test_apply_shortlists_new_application(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1,), jobs_per_user=1)
    (s,) = _scorers(prefs, facts, users=(1,))
    score_round_robin(conn, [s], FakeLLM(handler=lambda sc, p: SCORE), rubric, _cfg(), NOW)
    assert conn.execute("SELECT status FROM applications WHERE user_id = 1").fetchone()[0] in ("shortlisted", "new")
    assert s.stats.shortlisted == (1 if conn.execute("SELECT recommendation FROM scores").fetchone()[0] == "apply" else 0)


def _onboard(conn, users):
    for u in users:
        conn.execute("""INSERT OR REPLACE INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at,
                        updated_at) VALUES (?, '{}', 1, NULL, 't', 't')""", (u,))
    conn.commit()


def test_one_user_run_gets_only_its_slice_of_the_global_cap(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2, 3, 4), jobs_per_user=60)
    _onboard(conn, (1, 2, 3, 4))
    scorers = _scorers(prefs, facts, users=(1,))  # a Fetch now run among 4 eligible users
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=150), NOW)
    assert scorers[0].stats.scored == 150 // 4
    assert scorers[0].stats.stopped_by == "share"


def test_disabled_and_unonboarded_users_do_not_dilute_the_share(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2, 3, 4), jobs_per_user=90)
    _onboard(conn, (1, 2, 3))
    conn.execute("UPDATE users SET disabled_at = 't' WHERE id = 3")
    conn.commit()
    scorers = _scorers(prefs, facts, users=(1,))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=150), NOW)
    assert scorers[0].stats.scored == 150 // 2  # users 1 and 2 are eligible


def _spent(conn, service):
    return conn.execute("SELECT COALESCE(SUM(amount), 0) FROM usage WHERE service = ?", (service,)).fetchone()[0]


def test_every_failed_score_gives_its_unit_back(tmp_path, prefs, facts, rubric):
    import pytest

    from jobseeker.llm import LLMError
    conn = _setup(tmp_path, users=(1,), jobs_per_user=2)
    for exc in (LLMQuotaExceeded("gone"), LLMUnavailable("down"), LLMError("bad reply")):
        def fail(schema, prompt, exc=exc):
            raise exc
        score_round_robin(conn, _scorers(prefs, facts, users=(1,)), FakeLLM(handler=fail), rubric, _cfg(), NOW)
        assert _spent(conn, "score") == 0, type(exc).__name__

    def crash(schema, prompt):
        raise RuntimeError("bug")
    with pytest.raises(RuntimeError):
        score_round_robin(conn, _scorers(prefs, facts, users=(1,)), FakeLLM(handler=crash), rubric, _cfg(), NOW)
    assert _spent(conn, "score") == 0


def _onboard(conn, users):
    for u in users:
        conn.execute("""INSERT OR REPLACE INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at,
                        updated_at) VALUES (?, '{}', 1, NULL, 't', 't')""", (u,))
    conn.commit()


def _use(conn, uid, amount):
    from jobseeker.clock import app_now
    conn.execute("INSERT INTO usage (user_id, period, service, amount) VALUES (?, ?, 'score', ?)",
                 (uid, app_now(NOW).strftime("%Y-%m-%d"), amount))
    conn.commit()


def _left(conn, cap):
    from jobseeker.clock import app_now
    used = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM usage WHERE period = ? AND service = 'score'",
                        (app_now(NOW).strftime("%Y-%m-%d"),)).fetchone()[0]
    return cap - used


def test_run_leaves_a_floor_for_users_who_have_not_scored_today(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2, 3), jobs_per_user=40)
    _onboard(conn, (1, 2, 3))
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (9, 'deleted-9@invalid', 't')")
    _use(conn, 9, 10)  # a tombstone's spend still counts: 20 of 30 left
    scorers = _scorers(prefs, facts, users=(1,))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=30), NOW)
    # share 10, floor 10, reserved 10 x 2 (users 2 and 3) = 20, pool 0
    assert scorers[0].stats.scored == 0 and scorers[0].stats.stopped_by == "reserved"


def test_no_reservation_once_the_others_have_scored(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, jobs_per_user=40)
    _onboard(conn, (1, 2, 3))
    _use(conn, 2, 1)
    _use(conn, 3, 1)
    scorers = _scorers(prefs, facts, users=(1,))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=30), NOW)
    assert scorers[0].stats.scored == 10  # its share, as before


def test_two_users_in_a_run_cannot_jointly_eat_the_reserve(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2, 3), jobs_per_user=40)
    _onboard(conn, (1, 2, 3))
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (9, 'deleted-9@invalid', 't')")
    _use(conn, 9, 12)  # 18 of 30 left; user 3 (not in the run) is owed a floor of 10, so this run may spend 8
    scorers = _scorers(prefs, facts, users=(1, 2))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=30, batch=2), NOW)
    assert sum(s.stats.scored for s in scorers) == 8 and _left(conn, 30) == 10
    assert {s.stats.stopped_by for s in scorers} == {"reserved"}


def test_whole_run_has_no_reserve(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2, 3), jobs_per_user=40)
    _onboard(conn, (1, 2, 3))
    scorers = _scorers(prefs, facts)
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=30), NOW)
    assert [s.stats.scored for s in scorers] == [10, 10, 10]


def test_users_with_no_scores_today_go_first(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2), jobs_per_user=12)
    _use(conn, 1, 1)
    order = []
    import jobseeker.pipeline.score as score_mod
    real = score_mod.save_score
    score_mod.save_score = lambda c, uid, *a, **k: order.append(uid) or real(c, uid, *a, **k)
    try:
        score_round_robin(conn, _scorers(prefs, facts, users=(1, 2)), FakeLLM(handler=lambda s, p: SCORE), rubric,
                          _cfg(global_scores=30), NOW)
    finally:
        score_mod.save_score = real
    assert order[0] == 2
