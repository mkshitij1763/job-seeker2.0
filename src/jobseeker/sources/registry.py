from __future__ import annotations

from collections.abc import Iterable

from jobseeker.config import Company, SearchConfig
from jobseeker.pipeline.normalize import normalize_company
from jobseeker.sources.ashby import AshbySource
from jobseeker.sources.base import Source
from jobseeker.sources.greenhouse import GreenhouseSource
from jobseeker.sources.jobspy_source import JobSpySource
from jobseeker.sources.lever import LeverSource

_ATS = {"greenhouse": GreenhouseSource, "lever": LeverSource, "ashby": AshbySource}


def build_sources(companies: list[Company], discovered: Iterable[tuple[str, Company]] = (),
                  search: SearchConfig | None = None) -> list[Source]:
    sources: list[Source] = [_ATS[c.ats](c) for c in companies]
    names = {normalize_company(c.name) for c in companies}
    boards = {(c.ats, c.slug) for c in companies}
    for norm, company in discovered:
        if norm in names or (company.ats, company.slug) in boards:
            continue
        src = _ATS[company.ats](company)
        src.discovered_as = norm  # lets the run mark a vanished board inactive
        sources.append(src)
        names.add(norm)
        boards.add((company.ats, company.slug))
    if search is not None:
        sources += [JobSpySource(site, search) for site in search.sites]
    return sources
