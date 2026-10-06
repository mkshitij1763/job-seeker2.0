from datetime import UTC, datetime

from jobseeker.db.applications import get_drafts, get_status
from jobseeker.db.core import connect
from jobseeker.db.runs import last_run
from jobseeker.llm import LLMError, LLMQuotaExceeded
from jobseeker.models import RawJob
from jobseeker.outreach.drafter import DraftBundle
from jobseeker.pipeline.run import run_daily
from jobseeker.scoring.scorer import LLMScore
from tests.fakes import FakeLLM

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


class StaticSource:
    def __init__(self, name, jobs=None, error=None):
        self.name, self.jobs, self.error = name, jobs or [], error

    def fetch(self, client):
        if self.error:
            raise self.error
        return self.jobs


def raw(**kw):
    base = dict(source="lever", source_job_id="1", company="CRED", title="Senior Product Analyst",
                location="Bengaluru", jd_text="SQL and A/B testing, 2-4 years of experience. Sessions of 15 minutes.",
                apply_url="https://jobs.lever.co/cred/1", posted_at=NOW)
    base.update(kw)
    return RawJob(**base)


SCORE = dict(role_family="senior_product_analyst", required_years=2, role_fit=30, experience_fit=25,
             skills_match=15, company=15, location_pay=7, matches=["SQL"], gaps=[])
DRAFT = dict(contact_role="Analytics Lead", contact_reason="Owns hire", email_subject="Analyst, 67% fewer errors",
             email_body="Your team runs A/B tests. I cut errors by 67% across 480K+ tests. 15 minutes?",
             li_note="Product analyst, 67% fewer errors via A/B tests. Keen to connect.", li_dm="Thanks! 15 minutes?")


def handler(schema, prompt):
    return SCORE if schema is LLMScore else DRAFT


def _run(conn, sources, llm, prefs, rubric, facts):
    return run_daily(conn, sources=sources, client=None, llm=llm, facts=facts, prefs=prefs, rubric=rubric, now=NOW)


def test_full_run_scores_shortlists_and_drafts(prefs, rubric, facts):
    conn = connect(":memory:")
    stats = _run(conn, [StaticSource("lever:cred", [raw()])], FakeLLM(handler=handler), prefs, rubric, facts)
    assert (stats.fetched, stats.new, stats.scored, stats.shortlisted, stats.drafted) == (1, 1, 1, 1, 1)
    assert get_status(conn, 1) == "drafted"
    assert set(get_drafts(conn, 1)) == {"email", "li_note", "li_dm"}
    assert last_run(conn)["finished_at"] is not None


def test_run_dedups_across_sources(prefs, rubric, facts):
    conn = connect(":memory:")
    dup = raw(source="greenhouse", source_job_id="gh-1", company="Cred", title="Sr. Product Analyst",
              location="Bangalore, Karnataka, IN", apply_url="https://linkedin.com/jobs/view/1")
    stats = _run(conn, [StaticSource("lever:cred", [raw()]), StaticSource("greenhouse:cred", [dup])],
                 FakeLLM(handler=handler), prefs, rubric, facts)
    assert (stats.new, stats.duplicates, stats.scored) == (1, 1, 1)
    assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1


def test_failing_source_and_llm_errors_do_not_abort(prefs, rubric, facts):
    conn = connect(":memory:")
    llm = FakeLLM(handler=lambda schema, prompt: LLMError("boom"))
    stats = _run(conn, [StaticSource("greenhouse:x", error=RuntimeError("404")),
                        StaticSource("lever:cred", [raw()])], llm, prefs, rubric, facts)
    assert stats.new == 1 and stats.scored == 0
    assert any("greenhouse:x" in e for e in stats.errors) and any("score job" in e for e in stats.errors)
    # next run retries scoring of the same job
    stats2 = _run(conn, [], FakeLLM(handler=handler), prefs, rubric, facts)
    assert stats2.scored == 1


def test_filtered_jobs_are_not_scored(prefs, rubric, facts):
    conn = connect(":memory:")
    stats = _run(conn, [StaticSource("lever:cred", [raw(title="Sales Manager")])], FakeLLM(handler=handler),
                 prefs, rubric, facts)
    assert (stats.filtered, stats.scored) == (1, 0)


def test_quota_exhausted_stops_llm_work(prefs, rubric, facts):
    conn = connect(":memory:")
    llm = FakeLLM(handler=lambda schema, prompt: LLMQuotaExceeded("daily quota used up"))
    jobs = [raw(source_job_id=str(i), title=f"Product Analyst {i}") for i in range(3)]
    stats = _run(conn, [StaticSource("lever:cred", jobs)], llm, prefs, rubric, facts)
    assert len(llm.calls) == 1 and stats.scored == 0 and stats.new == 3
    assert any("quota" in e for e in stats.errors)


def test_budget_limits_scoring(prefs, rubric, facts):
    conn = connect(":memory:")
    prefs.budgets.score_per_run = 2
    jobs = [raw(source_job_id=str(i), title=f"Product Analyst {i}") for i in range(5)]
    stats = _run(conn, [StaticSource("lever:cred", jobs)], FakeLLM(handler=handler), prefs, rubric, facts)
    assert stats.scored == 2


def test_run_records_actual_finish_time(prefs, rubric, facts):
    from datetime import timedelta

    conn = connect(":memory:")
    times = iter([NOW, NOW + timedelta(minutes=5)])
    run_daily(conn, sources=[], client=None, llm=FakeLLM(handler=handler), facts=facts, prefs=prefs,
              rubric=rubric, clock=lambda: next(times))
    run = last_run(conn)
    assert run["started_at"] == "2026-10-07T02:00:00+00:00"
    assert run["finished_at"] == "2026-10-07T02:05:00+00:00"
