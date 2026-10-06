from __future__ import annotations

import re
from datetime import datetime

from jobseeker.config import Preferences
from jobseeker.models import Job
from jobseeker.pipeline.normalize import normalize_company

_YEARS = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*\d{1,2}\s*\+?)?\s*(?:years?|yrs?)\b", re.I)
_EXP = re.compile(r"\bexp(?:erience)?\b", re.I)


def min_years_required(text: str) -> int | None:
    found = []
    for m in _YEARS.finditer(text):
        window = text[max(0, m.start() - 40): m.end() + 40]
        if _EXP.search(window):
            found.append(int(m.group(1)))
    return min(found) if found else None


def prefilter(job: Job, prefs: Preferences, now: datetime, blocked: set[str]) -> str | None:
    if normalize_company(job.company) in blocked:
        return "blocked company"
    title = job.title.lower()
    for term in prefs.title_deny:
        if re.search(rf"\b{re.escape(term.lower())}\b", title):
            return f"title: {term}"
    if prefs.title_allow and not any(term.lower() in title for term in prefs.title_allow):
        return "title: not a target role"
    cities = {c.lower() for c in prefs.cities}
    loc = job.location.strip().lower()
    if job.location_city not in cities and loc:
        indian = "india" in loc or job.location_city is not None or loc == "remote"
        if not (job.is_remote and prefs.remote_india_ok and indian):
            return f"location: {job.location}"
    years = min_years_required(job.jd_text)
    if years is not None and years >= prefs.drop_if_min_years_at_least:
        return f"experience: {years}+ years"
    if job.posted_at is not None:
        age = (now - job.posted_at).days
        if age > prefs.max_age_days:
            return f"stale: posted {age} days ago"
    return None
