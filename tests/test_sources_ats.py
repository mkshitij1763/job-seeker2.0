import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from jobseeker.config import Company
from jobseeker.sources.ashby import AshbySource
from jobseeker.sources.greenhouse import GreenhouseSource
from jobseeker.sources.http import get_json
from jobseeker.sources.lever import LeverSource

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


@respx.mock
def test_greenhouse_parses_escaped_content():
    respx.get("https://boards-api.greenhouse.io/v1/boards/groww/jobs").respond(json=load("greenhouse_min.json"))
    jobs = GreenhouseSource(Company(name="Groww", ats="greenhouse", slug="groww")).fetch(httpx.Client())
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.source, j.source_job_id, j.company) == ("greenhouse", "4970739101", "Groww")
    assert j.jd_text == "Own funnels & experiments.\n3+ years of experience"
    assert j.posted_at == datetime(2026, 10, 4, 7, 49, 28, tzinfo=UTC)
    assert j.location == "Bengaluru-VTP, India"


@respx.mock
def test_lever_parses_lists_salary_locations():
    respx.get("https://api.lever.co/v0/postings/cred").respond(json=load("lever_min.json"))
    [j] = LeverSource(Company(name="CRED", ats="lever", slug="cred")).fetch(httpx.Client())
    assert j.title == "Product Analyst" and j.location == "bangalore, pune"
    assert "Requirements\nSQL\n2-4 years of experience" in j.jd_text
    assert j.salary_text == "2500000–3200000 INR per-year-salary"
    assert j.remote is False and j.posted_at.year == 2026
    assert j.apply_url == "https://jobs.lever.co/cred/aa98a938"


@respx.mock
def test_ashby_skips_unlisted_and_reads_comp():
    respx.get("https://api.ashbyhq.com/posting-api/job-board/sarvam").respond(json=load("ashby_min.json"))
    jobs = AshbySource(Company(name="Sarvam AI", ats="ashby", slug="sarvam")).fetch(httpx.Client())
    assert [j.source_job_id for j in jobs] == ["f337"]
    assert jobs[0].salary_text == "₹30L – ₹45L"
    assert jobs[0].location == "Bengaluru, Remote - India" and jobs[0].remote is True


@pytest.mark.parametrize("name,cls,ats,slug,url", [
    ("greenhouse_groww.json", GreenhouseSource, "greenhouse", "groww", "https://boards-api.greenhouse.io/v1/boards/groww/jobs"),
    ("lever_cred.json", LeverSource, "lever", "cred", "https://api.lever.co/v0/postings/cred"),
    ("ashby_sarvam.json", AshbySource, "ashby", "sarvam", "https://api.ashbyhq.com/posting-api/job-board/sarvam"),
])
@respx.mock
def test_recorded_real_payloads_parse(name, cls, ats, slug, url):
    respx.get(url).respond(json=load(name))
    jobs = cls(Company(name="X", ats=ats, slug=slug)).fetch(httpx.Client())
    assert jobs and all(j.title and j.apply_url.startswith("http") for j in jobs)
    assert all("&lt;" not in j.jd_text for j in jobs)


@respx.mock
def test_get_json_retries_then_succeeds():
    route = respx.get("https://api.example/x").mock(side_effect=[
        httpx.Response(503), httpx.Response(429), httpx.Response(200, json={"ok": True})])
    assert get_json(httpx.Client(), "https://api.example/x", sleep=lambda s: None) == {"ok": True}
    assert route.call_count == 3


@respx.mock
def test_get_json_raises_on_404():
    respx.get("https://api.example/y").respond(404)
    with pytest.raises(httpx.HTTPStatusError):
        get_json(httpx.Client(), "https://api.example/y", sleep=lambda s: None)
