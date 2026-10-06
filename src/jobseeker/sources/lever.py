from __future__ import annotations

import httpx

from jobseeker.config import Company
from jobseeker.models import RawJob
from jobseeker.pipeline.normalize import html_to_text
from jobseeker.sources.base import from_epoch_ms
from jobseeker.sources.http import get_json


def _salary(p: dict) -> str | None:
    s = p.get("salaryRange")
    if not s or s.get("min") is None:
        return None
    return f"{s['min']}–{s.get('max', s['min'])} {s.get('currency', '')} {s.get('interval', '')}".strip()


class LeverSource:
    def __init__(self, company: Company):
        self.company = company
        self.name = f"lever:{company.slug}"

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        data = get_json(client, f"https://api.lever.co/v0/postings/{self.company.slug}", params={"mode": "json"})
        jobs = []
        for p in data:
            cats = p.get("categories") or {}
            locs = cats.get("allLocations") or [cats.get("location", "")]
            sections = [p.get("descriptionPlain", "")]
            sections += [f"{li.get('text', '')}\n{html_to_text(li.get('content', ''))}" for li in p.get("lists", [])]
            sections.append(p.get("additionalPlain", ""))
            jobs.append(RawJob(
                source="lever", source_job_id=p["id"], company=self.company.name, title=p["text"],
                location=", ".join(loc for loc in locs if loc),
                remote=p.get("workplaceType") == "remote",
                posted_at=from_epoch_ms(p.get("createdAt")), salary_text=_salary(p),
                jd_text="\n\n".join(s.strip() for s in sections if s and s.strip()),
                apply_url=p.get("hostedUrl") or p.get("applyUrl"),
            ))
        return jobs
