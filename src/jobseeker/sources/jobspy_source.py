from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from jobseeker.config import SearchConfig
from jobseeker.models import RawJob
from jobseeker.pipeline.normalize import canonical_city
from jobseeker.sources.base import parse_iso

Scrape = Callable[..., list[dict[str, Any]]]
_PAUSE = {"linkedin": 3.0, "naukri": 1.0, "indeed": 1.0}  # seconds between searches, to stay polite


def jobspy_scrape(**kwargs) -> list[dict[str, Any]]:
    from jobspy import scrape_jobs

    df = scrape_jobs(**kwargs)
    return json.loads(df.to_json(orient="records", date_format="iso"))  # NaN -> None, dates -> ISO strings


def fetch_description(source: str, source_job_id: str) -> str:
    """Full description of one job-site posting. Only LinkedIn search results lack one."""
    if source != "linkedin":
        return ""
    from jobspy.linkedin import LinkedIn
    from jobspy.model import DescriptionFormat, ScraperInput, Site

    scraper = LinkedIn()
    scraper.scraper_input = ScraperInput(site_type=[Site.LINKEDIN], description_format=DescriptionFormat.MARKDOWN)
    details = scraper._get_job_details(source_job_id.removeprefix("li-")) or {}  # private in jobspy 1.2.0
    return (details.get("description") or "").strip()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _salary(row: dict) -> str | None:
    low, high = row.get("min_amount"), row.get("max_amount")
    if low is None:
        return None
    return f"{int(low)}–{int(high if high is not None else low)} {_text(row.get('currency'))} " \
           f"{_text(row.get('interval'))}".strip()


def to_raw_job(site: str, row: dict, search_location: str) -> RawJob | None:
    job_id, title, company, url = (_text(row.get(k)) for k in ("id", "title", "company", "job_url"))
    if not (job_id and title and company and url):
        return None
    location = _text(row.get("location"))
    if canonical_city(location) is None and search_location != "India":
        # Indeed India often reports only the state ("KA, IN"); the searched city is the better signal.
        location = f"{search_location}, {location}" if location else search_location
    description = _text(row.get("description"))
    experience = _text(row.get("experience_range"))
    if experience:
        description = f"Experience: {experience}\n\n{description}".strip()
    remote = row.get("is_remote") is True or _text(row.get("work_from_home_type")).lower() == "remote"
    return RawJob(source=site, source_job_id=job_id, company=company, title=title, location=location,
                  remote=remote, posted_at=parse_iso(_text(row.get("date_posted")) or None),
                  salary_text=_salary(row), jd_text=description, apply_url=url)


class JobSpySource:
    discovers = True  # companies seen here feed board discovery

    def __init__(self, site: str, search: SearchConfig, scrape: Scrape = jobspy_scrape,
                 sleep: Callable[[float], None] = time.sleep):
        self.site, self.search, self.scrape, self.sleep = site, search, scrape, sleep
        self.name = site
        self.warnings: list[str] = []

    def searches(self) -> list[tuple[str, str]]:
        if self.site == "linkedin":
            locations = ["India"]  # one search per query keeps LinkedIn under its rate limit
        else:
            locations = list(self.search.locations) + (["India"] if self.search.remote_query else [])
        return [(q, loc) for q in self.search.queries for loc in locations]

    def fetch(self, client: httpx.Client | None) -> list[RawJob]:
        self.warnings = []
        plan = self.searches()
        jobs: list[RawJob] = []
        seen: set[str] = set()
        for i, (query, location) in enumerate(plan):
            if i:
                self.sleep(_PAUSE.get(self.site, 1.0))
            try:
                rows = self.scrape(site_name=[self.site], search_term=query, location=location,
                                   results_wanted=self.search.results_per_search, hours_old=self.search.hours_old,
                                   country_indeed="india", description_format="markdown",
                                   fetch_description=self.site == "naukri", verbose=0)
            except Exception as e:
                if not jobs:
                    raise
                self.warnings.append(f"stopped after {i} of {len(plan)} searches: {type(e).__name__}: {e}")
                break
            for row in rows:
                job = to_raw_job(self.site, row, location)
                if job and job.source_job_id not in seen:
                    seen.add(job.source_job_id)
                    jobs.append(job)
        return jobs
