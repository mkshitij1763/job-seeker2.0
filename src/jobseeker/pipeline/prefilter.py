from __future__ import annotations

import re
from datetime import datetime

from jobseeker.config import Preferences
from jobseeker.models import Job
from jobseeker.pipeline.normalize import normalize_company

_YEARS = re.compile(
    r"(\d{1,2}(?:\.\d+)?)\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*\d{1,2}(?:\.\d+)?\s*\+?)?\s*(?:years?|yrs?)\b", re.I)
# A number counts only when experience follows it ("3+ years of product experience") or a requirement
# label precedes it ("Experience: 5 years", "at least 4 years"); "10 years ago" never counts.
_EXP_AFTER = re.compile(r"(?!\s+(?:ago|old)\b)\s+(?:of\s+)?(?:[\w/&-]+\s+){0,3}?exp(?:erience)?\b", re.I)
_LABEL_BEFORE = re.compile(r"(?:\bexp(?:erience)?\s*[:\-–]?|\bminimum(?:\s+of)?|\bat\s+least)\s*$", re.I)
# "7+ years in product analytics", "3-5 years as a PM": a plus sign or a range marks a requirement.
_FIELD_AFTER = re.compile(r"\s+(?:in|as|working)\b", re.I)
_PLUS_OR_RANGE = re.compile(r"\+|plus|-|–|—|\bto\b", re.I)


def min_years_required(text: str) -> float | None:
    found = []
    for m in _YEARS.finditer(text):
        qualified = _PLUS_OR_RANGE.search(m.group(0)) and _FIELD_AFTER.match(text, m.end())
        if qualified or _EXP_AFTER.match(text, m.end()) or _LABEL_BEFORE.search(text[max(0, m.start() - 30): m.start()]):
            found.append(float(m.group(1)))
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
        return f"experience: {years:g}+ years"
    if job.posted_at is not None:
        age = (now - job.posted_at).days
        if age > prefs.max_age_days:
            return f"stale: posted {age} days ago"
    return None
