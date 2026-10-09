"""Stage 2: fetch every planned source once and store jobs. No per-user verdicts, no AI."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from jobseeker.db.companies import bump_jobs_seen, mark_inactive, record_board_fetch
from jobseeker.db.jobs import upsert_job
from jobseeker.pipeline.discovery import discover
from jobseeker.pipeline.normalize import normalize, normalize_company, normalize_title


@dataclass
class FetchStats:
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    discovered: int = 0
    searches_planned: int = 0
    searches_run: int = 0
    searches_trimmed: int = 0
    searches_total: int = 0
    described: int = 0
    errors: list[str] = field(default_factory=list)


def fetch_shared(conn, sources, client, now: datetime, generic_words: set[str], stats: FetchStats,
                 heartbeat: Callable[[], None] = lambda: None) -> FetchStats:
    known = {normalize_company(s.company.name) for s in sources if hasattr(s, "company")}
    seen: dict[str, tuple[str, set[str]]] = {}
    unrecorded: Counter[str] = Counter()  # jobs at companies discovery may record later this run
    for src in sources:
        try:
            raws = src.fetch(client)
        except Exception as e:  # one broken source must never kill the run
            stats.errors.append(f"{src.name}: {type(e).__name__}: {e}")
            norm = getattr(src, "discovered_as", None)
            if norm and isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                mark_inactive(conn, norm, now)
            heartbeat()
            continue
        stats.errors += [f"{src.name}: {w}" for w in getattr(src, "warnings", [])]
        stats.searches_run += len(src.searches()) if hasattr(src, "searches") else 0
        stats.fetched += len(raws)
        for r in raws:
            job = normalize(r)
            if getattr(src, "discovers", False):
                seen.setdefault(normalize_company(job.company), (job.company, set()))[1].add(normalize_title(job.title))
            _, is_new = upsert_job(conn, job, now)
            if is_new:
                stats.new += 1
                norm = normalize_company(job.company)
                if not bump_jobs_seen(conn, norm):
                    unrecorded[norm] += 1
            else:
                stats.duplicates += 1
        if hasattr(src, "company"):  # an ATS board whose jobs are stored: Fetch now skips it for a while
            record_board_fetch(conn, src.name, now)
        heartbeat()
    if client is not None and seen:
        stats.discovered = discover(conn, client, seen, known, now, generic=generic_words)
        for norm, n in unrecorded.items():
            bump_jobs_seen(conn, norm, n)
    return stats
