import json
from pathlib import Path

import pytest

from jobseeker.config import SearchConfig
from jobseeker.sources.jobspy_source import JobSpySource, fetch_description, to_raw_job

FIX = Path(__file__).parent / "fixtures"


def rows(site):
    return json.loads((FIX / f"jobspy_{site}.json").read_text())


def fake_scrape(table):
    calls = []

    def scrape(**kw):
        calls.append(kw)
        out = table(kw) if callable(table) else table
        if isinstance(out, Exception):
            raise out
        return out
    scrape.calls = calls
    return scrape


@pytest.mark.parametrize("site", ["linkedin", "naukri", "indeed"])
def test_recorded_rows_map_to_raw_jobs(site):
    jobs = [to_raw_job(site, r, "Bengaluru" if site != "linkedin" else "India") for r in rows(site)]
    jobs = [j for j in jobs if j]
    assert jobs and all(j.source == site and j.title and j.company and j.apply_url.startswith("http") for j in jobs)


def test_search_plan_per_site():
    search = SearchConfig()
    assert len(JobSpySource("linkedin", search).searches()) == 5
    assert JobSpySource("linkedin", search).searches()[0] == ("Product Analyst", "India")
    naukri = JobSpySource("naukri", search).searches()
    assert len(naukri) == 25 and ("Product Analyst", "Pune") in naukri and ("Product Analyst", "India") in naukri
    no_remote = SearchConfig(remote_query=False)
    assert len(JobSpySource("indeed", no_remote).searches()) == 20


def test_fetch_passes_site_options_and_dedups():
    row = {"id": "nk-1", "title": "APM", "company": "Tracxn", "location": "Bengaluru, India",
           "job_url": "https://naukri.com/1", "description": "d"}
    scrape = fake_scrape([row])
    src = JobSpySource("naukri", SearchConfig(queries=["APM"], locations=["Bengaluru"]), scrape=scrape,
                       sleep=lambda s: None)
    jobs = src.fetch(None)
    assert len(jobs) == 1 and len(scrape.calls) == 2  # Bengaluru + India, same job once
    kw = scrape.calls[0]
    assert kw["site_name"] == ["naukri"] and kw["fetch_description"] is True
    assert kw["country_indeed"] == "india" and kw["hours_old"] == 72 and kw["results_wanted"] == 25


def test_partial_failure_keeps_jobs_and_warns():
    row = {"id": "li-1", "title": "PM", "company": "X", "location": "Pune, India", "job_url": "https://l/1"}
    seq = iter([[row], RuntimeError("429 Too Many Requests")])
    src = JobSpySource("linkedin", SearchConfig(queries=["PM", "APM", "PA"]),
                       scrape=fake_scrape(lambda kw: next(seq)), sleep=lambda s: None)
    jobs = src.fetch(None)
    assert [j.source_job_id for j in jobs] == ["li-1"]
    assert len(src.warnings) == 1 and "429" in src.warnings[0] and "1 of 3" in src.warnings[0]


def test_first_failure_raises():
    src = JobSpySource("linkedin", SearchConfig(), scrape=fake_scrape(RuntimeError("blocked")),
                       sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        src.fetch(None)


def test_rows_missing_required_fields_are_skipped():
    assert to_raw_job("naukri", {"id": "1", "title": "PM", "company": None, "job_url": "https://x"}, "Pune") is None
    assert to_raw_job("naukri", {"id": "1", "title": "", "company": "C", "job_url": "https://x"}, "Pune") is None
    assert to_raw_job("naukri", {"id": None, "title": "PM", "company": "C", "job_url": "https://x"}, "Pune") is None


def test_indeed_state_only_location_gets_search_city():
    job = to_raw_job("indeed", {"id": "in-1", "title": "PA", "company": "C", "location": "KA, IN",
                                "job_url": "https://in.indeed.com/1"}, "Bengaluru")
    assert job.location == "Bengaluru, KA, IN"
    remote = to_raw_job("indeed", {"id": "in-2", "title": "PA", "company": "C", "location": "IN",
                                   "job_url": "https://in.indeed.com/2"}, "India")
    assert remote.location == "IN"


def test_naukri_experience_salary_remote_and_date():
    job = to_raw_job("naukri", {
        "id": "nk-9", "title": "APM", "company": "C", "location": "Pune, India", "job_url": "https://n/9",
        "experience_range": "6-11 Yrs", "description": "Build things.", "work_from_home_type": "Remote",
        "min_amount": 1500000, "max_amount": 2500000, "currency": "INR", "interval": "yearly",
        "date_posted": "2026-10-06T00:00:00.000"}, "Pune")
    assert job.jd_text == "Experience: 6-11 Yrs\n\nBuild things."
    assert job.remote is True and job.salary_text == "1500000–2500000 INR yearly"
    assert job.posted_at.isoformat() == "2026-10-06T00:00:00+00:00"


def test_fetch_description_only_for_linkedin():
    assert fetch_description("naukri", "nk-1") == ""


def test_empty_searches_are_reported():
    row = {"id": "li-1", "title": "PM", "company": "X", "location": "Pune, India", "job_url": "https://l/1"}
    seq = iter([[row], [], []])
    src = JobSpySource("linkedin", SearchConfig(queries=["PM", "APM", "PA"]),
                       scrape=fake_scrape(lambda kw: next(seq)), sleep=lambda s: None)
    assert len(src.fetch(None)) == 1
    assert src.warnings == ["2 of 3 searches returned no results (the site may be rate-limiting)"]


def test_unknown_city_is_not_relabelled_as_searched_city():
    job = to_raw_job("naukri", {"id": "nk-1", "title": "PA", "company": "C", "location": "Ahmedabad",
                                "job_url": "https://n/1"}, "Bengaluru")
    assert job.location == "Ahmedabad"
    empty = to_raw_job("naukri", {"id": "nk-2", "title": "PA", "company": "C", "location": "",
                                  "job_url": "https://n/2"}, "Pune")
    assert empty.location == "Pune"


def test_naukri_row_without_description_has_empty_jd():
    # Naukri's detail fetch can fail (e.g. HTTP 406); an "Experience: …" stub must not stand in for a description,
    # or it overwrites the full one stored earlier and triggers a re-score on almost no text.
    job = to_raw_job("naukri", {"id": "nk-1", "title": "APM", "company": "C", "location": "Pune, India",
                                "job_url": "https://n/1", "experience_range": "1-3 Yrs", "description": None}, "Pune")
    assert job.jd_text == ""


def test_plan_overrides_searches():
    from jobseeker.config import SearchConfig
    from jobseeker.sources.jobspy_source import JobSpySource

    calls = []
    src = JobSpySource("naukri", SearchConfig(), scrape=lambda **kw: calls.append((kw["search_term"], kw["location"])) or [],
                       sleep=lambda s: None, plan=[("Data Analyst", "Mumbai")])
    src.fetch(None)
    assert calls == [("Data Analyst", "Mumbai")]
