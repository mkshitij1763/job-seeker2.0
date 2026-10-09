from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.db.runs import finish_run, header_run, start_run
from jobseeker.web.filters import explain_stats

NOW = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)


def test_user_sees_own_and_fetch_errors_only(settings, seeded_two):
    conn = connect(settings.db_path)
    f = start_run(conn, NOW, None, kind="fetch", trigger="schedule")
    finish_run(conn, f, {"searches_trimmed": 4, "searches_planned": 60}, ["naukri: 3 of 25 searches returned no results"], NOW)
    for uid, err in ((1, "score job 7: LLMError: x"), (2, "score job 9: LLMError: y")):
        r = start_run(conn, NOW, uid, kind="user", trigger="schedule", parent_id=f)
        finish_run(conn, r, {"stopped_by": "share", "score_share_left": 0}, [err], NOW)
    run, errors, stats = header_run(conn, 2)
    assert "score job 9: LLMError: y" in errors and "score job 7: LLMError: x" not in errors
    assert "naukri: 3 of 25 searches returned no results" in errors
    assert stats["user"]["stopped_by"] == "share" and stats["fetch"]["searches_trimmed"] == 4


def test_fetch_only_before_first_user_run(settings):
    conn = connect(settings.db_path)
    f = start_run(conn, NOW, None, kind="fetch", trigger="schedule")
    finish_run(conn, f, {}, ["greenhouse:x: HTTPStatusError: 404"], NOW)
    assert header_run(conn, 1)[1] == ["greenhouse:x: HTTPStatusError: 404"]


def test_explain_stats():
    texts = [n["text"] for n in explain_stats({"user": {"stopped_by": "share", "scored": 25},
                                               "fetch": {"searches_trimmed": 6, "searches_planned": 60,
                                                         "searches_run": 54}})]
    assert "You've used today's 25 scores; more tomorrow" in texts
    assert any(t.startswith("Searched 54 of 60 role and city combinations today") for t in texts)
    for reason in ("global_cap", "quota"):
        assert explain_stats({"user": {"stopped_by": reason}, "fetch": {}})[0]["text"] == \
            "The shared AI limit ran out today; scoring resumes tomorrow"
    assert all(not n["action"] for n in explain_stats({"user": {"stopped_by": "quota"}, "fetch": {"searches_trimmed": 1}}))
