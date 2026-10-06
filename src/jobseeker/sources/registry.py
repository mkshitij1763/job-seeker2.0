from __future__ import annotations

from jobseeker.config import Company
from jobseeker.sources.ashby import AshbySource
from jobseeker.sources.base import Source
from jobseeker.sources.greenhouse import GreenhouseSource
from jobseeker.sources.lever import LeverSource

_ATS = {"greenhouse": GreenhouseSource, "lever": LeverSource, "ashby": AshbySource}


def build_sources(companies: list[Company]) -> list[Source]:
    # Phase 2: append JobSpy / Apify sources here.
    return [_ATS[c.ats](c) for c in companies]
