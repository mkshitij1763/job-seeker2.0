from __future__ import annotations

import httpx

from jobseeker.config import Company
from jobseeker.models import RawJob
from jobseeker.pipeline.normalize import html_to_text
from jobseeker.sources.base import parse_iso
from jobseeker.sources.http import get_json


class GreenhouseSource:
    def __init__(self, company: Company):
        self.company = company
        self.name = f"greenhouse:{company.slug}"

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        data = get_json(client, f"https://boards-api.greenhouse.io/v1/boards/{self.company.slug}/jobs",
                        params={"content": "true"})
        return [
            RawJob(
                source="greenhouse", source_job_id=str(j["id"]), company=self.company.name,
                title=j["title"], location=(j.get("location") or {}).get("name", ""),
                posted_at=parse_iso(j.get("first_published") or j.get("updated_at")),
                jd_text=html_to_text(j.get("content", "")), apply_url=j["absolute_url"],
            )
            for j in data.get("jobs", [])
        ]
