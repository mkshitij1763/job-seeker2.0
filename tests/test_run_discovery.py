from datetime import UTC, datetime, timedelta

import httpx
import respx

from jobseeker.db.companies import active_companies, get_company, record_company
from jobseeker.db.core import connect
from jobseeker.db.jobs import get_job
from jobseeker.db.runs import last_run
from jobseeker.llm import LLMQuotaExceeded
from jobseeker.models import RawJob
from jobseeker.pipeline.run import run_daily
from jobseeker.scoring.scorer import LLMScore
from tests.fakes import FakeLLM

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)
SCORE = dict(role_family="product_analyst", required_years=2, role_fit=20, experience_fit=20, skills_match=10,
             company=10, location_pay=5, matches=["SQL"], gaps=[])
DRAFT = dict(contact_role="Lead", contact_reason="r", email_subject="s", email_body="b", li_note="n", li_dm="d")


def handler(schema, prompt):
    return SCORE if schema is LLMScore else DRAFT


class Src:
    def __init__(self, name, jobs=None, error=None, discovers=False, warnings=None, discovered_as=None):
        self.name, self.jobs, self.error = name, jobs or [], error
        self.discovers = discovers
        self.warnings = warnings or []
        if discovered_as:
            self.discovered_as = discovered_as

    def fetch(self, client):
        if self.error:
            raise self.error
        return self.jobs


def raw(**kw):
    base = dict(source="naukri", source_job_id="1", company="Tracxn", title="Product Analyst",
                location="Bengaluru", jd_text="SQL and A/B testing. 2-4 years of experience.",
                apply_url="https://n/1", posted_at=NOW)
    base.update(kw)
    return RawJob(**base)


def run(conn, sources, prefs, rubric, facts, llm=None, **kw):
    kw.setdefault("now", NOW)
    return run_daily(conn, sources=sources, client=kw.pop("client", None), llm=llm or FakeLLM(handler=handler),
                     facts=facts, prefs=prefs, rubric=rubric, **kw)


def scored_titles(conn):
    return [r[0] for r in conn.execute("SELECT j.title FROM scores s JOIN jobs j ON j.id = s.job_id ORDER BY s.id")]


def test_scoring_follows_prescore_order(prefs, rubric, facts):
    conn = connect(":memory:")
    prefs.budgets.score_per_run = 1
    weak = raw(source_job_id="w", title="Strategy Manager", jd_text="Plan things.")
    strong = raw(source_job_id="s", title="Product Analyst")
    stats = run(conn, [Src("naukri", [weak, strong])], prefs, rubric, facts)
    assert scored_titles(conn) == ["Product Analyst"] and stats.candidates == 2


def test_low_prescore_set_aside(prefs, rubric, facts):
    conn = connect(":memory:")
    prefs.min_prescore = 40
    stats = run(conn, [Src("naukri", [raw(title="Insights Manager", jd_text="Lorem ipsum.", location="")])],
                prefs, rubric, facts)
    assert stats.below_cutoff == 1 and stats.scored == 0
    assert get_job(conn, 1)["filter_reason"] == "low pre-score: 32"


def test_linkedin_description_fetched_before_scoring(prefs, rubric, facts):
    conn = connect(":memory:")
    calls = []

    def describe(source, job_id):
        calls.append((source, job_id))
        return "Own SQL dashboards. 1-3 years of experience."
    stats = run(conn, [Src("linkedin", [raw(source="linkedin", source_job_id="li-7", jd_text="")])],
                prefs, rubric, facts, describe=describe)
    assert calls == [("linkedin", "li-7")] and stats.scored == 1
    assert get_job(conn, 1)["jd_text"].startswith("Own SQL dashboards")


def test_linkedin_description_failure_waits(prefs, rubric, facts):
    conn = connect(":memory:")

    def describe(source, job_id):
        raise RuntimeError("429")
    stats = run(conn, [Src("linkedin", [raw(source="linkedin", source_job_id="li-7", jd_text="")])],
                prefs, rubric, facts, describe=describe)
    assert stats.scored == 0 and get_job(conn, 1)["filter_reason"] is None
    assert any("linkedin descriptions: 1 failed" in e for e in stats.errors)


def test_linkedin_description_cap(prefs, rubric, facts):
    conn = connect(":memory:")
    prefs.search.linkedin_descriptions_per_run = 1
    jobs = [raw(source="linkedin", source_job_id=f"li-{i}", title=f"Product Analyst {i}", jd_text="")
            for i in range(3)]
    calls = []
    run(conn, [Src("linkedin", jobs)], prefs, rubric, facts,
        describe=lambda s, j: calls.append(j) or "SQL. 2 years of experience.")
    assert len(calls) == 1


def test_fetched_description_with_8_plus_years_is_filtered(prefs, rubric, facts):
    conn = connect(":memory:")
    stats = run(conn, [Src("linkedin", [raw(source="linkedin", source_job_id="li-7", jd_text="")])],
                prefs, rubric, facts, describe=lambda s, j: "Needs 10+ years of experience.")
    assert stats.scored == 0 and get_job(conn, 1)["filter_reason"] == "experience: 10+ years"


def test_unscored_jobs_expire(prefs, rubric, facts):
    conn = connect(":memory:")
    quota = FakeLLM(handler=lambda schema, prompt: LLMQuotaExceeded("daily quota"))
    run(conn, [Src("naukri", [raw()])], prefs, rubric, facts, llm=quota)
    run(conn, [], prefs, rubric, facts, now=NOW + timedelta(days=8))
    assert get_job(conn, 1)["filter_reason"] == "stale: never scored"


@respx.mock
def test_discovery_from_job_site_companies(prefs, rubric, facts):
    respx.get("https://api.lever.co/v0/postings/tracxn").respond(json=[{"text": "Product Analyst, Payments"}])
    respx.route().respond(404)
    conn = connect(":memory:")
    job = raw(title="Product Analyst - Payments")
    stats = run(conn, [Src("naukri", [job], discovers=True)], prefs, rubric, facts, client=httpx.Client())
    assert stats.discovered == 1
    assert [n for n, _ in active_companies(conn)] == ["tracxn"]
    assert get_company(conn, "tracxn")["jobs_seen"] == 1  # the job that led to the discovery counts too


def test_discovered_board_404_marks_inactive(prefs, rubric, facts):
    conn = connect(":memory:")
    record_company(conn, "tracxn", "Tracxn", "active", "lever", "tracxn", NOW)
    gone = httpx.HTTPStatusError("404", request=httpx.Request("GET", "https://x"),
                                 response=httpx.Response(404))
    run(conn, [Src("lever:tracxn", error=gone, discovered_as="tracxn")], prefs, rubric, facts)
    assert get_company(conn, "tracxn")["status"] == "inactive"


def test_jobs_seen_counted_for_discovered_company(prefs, rubric, facts):
    conn = connect(":memory:")
    record_company(conn, "tracxn", "Tracxn", "active", "lever", "tracxn", NOW)
    run(conn, [Src("lever:tracxn", [raw(source="lever")])], prefs, rubric, facts)
    assert get_company(conn, "tracxn")["jobs_seen"] == 1


def test_source_warnings_recorded(prefs, rubric, facts):
    conn = connect(":memory:")
    stats = run(conn, [Src("linkedin", [raw()], warnings=["stopped after 2 of 5 searches"])],
                prefs, rubric, facts)
    assert "linkedin: stopped after 2 of 5 searches" in stats.errors


def test_unexpected_exception_still_finishes_run(prefs, rubric, facts):
    conn = connect(":memory:")
    stats = run(conn, [Src("broken", [None])], prefs, rubric, facts)
    assert any(e.startswith("run aborted:") for e in stats.errors)
    assert last_run(conn)["finished_at"] is not None


def test_jobs_without_description_do_not_block_scoring(prefs, rubric, facts):
    conn = connect(":memory:")
    prefs.budgets.score_per_run = 1
    prefs.search.linkedin_descriptions_per_run = 0
    li = [raw(source="linkedin", source_job_id=f"li-{i}", title=f"Product Analyst {i}", jd_text="")
          for i in range(2)]
    naukri = raw(source_job_id="nk", title="Strategy Manager", jd_text="Plan things.")
    stats = run(conn, [Src("linkedin", li), Src("naukri", [naukri])], prefs, rubric, facts)
    assert stats.scored == 1 and scored_titles(conn) == ["Strategy Manager"]


def test_empty_description_counts_as_failure_and_stops_after_two(prefs, rubric, facts):
    conn = connect(":memory:")
    jobs = [raw(source="linkedin", source_job_id=f"li-{i}", title=f"Product Analyst {i}", jd_text="")
            for i in range(4)]
    calls = []
    stats = run(conn, [Src("linkedin", jobs)], prefs, rubric, facts, describe=lambda s, j: calls.append(j) or "")
    assert len(calls) == 2
    assert any("linkedin descriptions: 2 failed" in e for e in stats.errors)


def test_job_skipped_after_two_failed_description_attempts(prefs, rubric, facts):
    conn = connect(":memory:")
    prefs.search.linkedin_descriptions_per_run = 1
    job = raw(source="linkedin", source_job_id="li-1", jd_text="")
    calls = []
    for _ in range(3):
        run(conn, [Src("linkedin", [job])], prefs, rubric, facts, describe=lambda s, j: calls.append(j) or "")
    assert len(calls) == 2


def test_rescore_makes_no_linkedin_description_calls(prefs, rubric, facts):
    conn = connect(":memory:")
    run(conn, [Src("linkedin", [raw(source="linkedin", source_job_id="li-9", jd_text="")])], prefs, rubric, facts,
        describe=lambda s, j: "")
    calls = []
    run(conn, [], prefs, rubric, facts, fetch=False, force_rescore=True,
        describe=lambda s, j: calls.append(j) or "Own the funnel.")
    assert calls == []  # rescore re-scores stored jobs; fetching from LinkedIn is the daily run's job
