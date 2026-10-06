from __future__ import annotations

import httpx

from jobseeker.config import Company
from jobseeker.models import RawJob
from jobseeker.pipeline.normalize import html_to_text
from jobseeker.sources.base import parse_iso
from jobseeker.sources.http import get_json


class AshbySource:
    def __init__(self, company: Company):
        self.company = company
        self.name = f"ashby:{company.slug}"

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        data = get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{self.company.slug}",
                        params={"includeCompensation": "true"})
        jobs = []
        for p in data.get("jobs", []):
            if p.get("isListed") is False:
                continue
            locs = [p.get("location", "")] + [s.get("location", "") for s in p.get("secondaryLocations") or []]
            jobs.append(RawJob(
                source="ashby", source_job_id=p["id"], company=self.company.name, title=p["title"],
                location=", ".join(loc for loc in locs if loc), remote=bool(p.get("isRemote")),
                posted_at=parse_iso(p.get("publishedAt")),
                salary_text=(p.get("compensation") or {}).get("compensationTierSummary"),
                jd_text=p.get("descriptionPlain") or html_to_text(p.get("descriptionHtml", "")),
                apply_url=p.get("jobUrl") or p.get("applyUrl"),
            ))
        return jobs
