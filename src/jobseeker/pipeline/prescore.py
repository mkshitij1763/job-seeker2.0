from __future__ import annotations

import re

from jobseeker.config import Preferences
from jobseeker.models import Job
from jobseeker.pipeline.normalize import normalize_title
from jobseeker.pipeline.prefilter import min_years_required
from jobseeker.profile.facts import Facts

# Cheap, local ranking used to spend the LLM budget on the most promising jobs (spec §4.3).
_TOP_TITLES = ("product analyst", "associate product manager", "founders office", "founder s office",
               "chief of staff")


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _title_points(job: Job, prefs: Preferences) -> int:
    title = normalize_title(job.title)
    if any(_has(title, t) for t in _TOP_TITLES):
        return 40
    if _has(title, "product manager"):
        return 35
    if any(_has(job.title.lower(), t.lower()) for t in prefs.title_allow):
        return 20
    return 5


def _skill_points(job: Job, facts: Facts) -> int:
    jd = job.jd_text.lower()
    if not jd.strip():
        return 15
    matched = sum(1 for s in facts.skills if s.strip() and _has(jd, s.strip().lower()))
    return min(30, 3 * matched)


def _experience_points(job: Job) -> int:
    years = min_years_required(job.jd_text)
    if years is None:
        return 12
    if years <= 3:
        return 20
    if years <= 5:
        return 12
    return 4


def _location_points(job: Job, prefs: Preferences) -> int:
    if job.location_city and job.location_city in {c.lower() for c in prefs.cities}:
        return 10
    return 8 if job.is_remote else 0


def prescore(job: Job, facts: Facts, prefs: Preferences) -> int:
    return (_title_points(job, prefs) + _skill_points(job, facts) + _experience_points(job)
            + _location_points(job, prefs))
