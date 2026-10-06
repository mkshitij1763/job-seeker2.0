from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RawJob(BaseModel):
    source: str
    source_job_id: str
    company: str
    title: str
    location: str = ""
    remote: bool | None = None
    posted_at: datetime | None = None
    salary_text: str | None = None
    jd_text: str = ""
    apply_url: str


class Job(RawJob):
    location_city: str | None = None
    is_remote: bool = False
    fingerprint: str


class ScoreResult(BaseModel):
    score: int
    breakdown: dict[str, int]
    matches: list[str]
    gaps: list[str]
    recommendation: Literal["apply", "review", "hide"]
    role_family: str


def jd_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
