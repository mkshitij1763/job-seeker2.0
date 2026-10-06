from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import datetime

import httpx

from jobseeker.db.companies import needs_check, record_company
from jobseeker.pipeline.normalize import normalize_company, normalize_title
from jobseeker.sources.http import get_json

MAX_PER_RUN = 20
BOARD_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{}/jobs",
    "lever": "https://api.lever.co/v0/postings/{}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{}",
}
GREENHOUSE_BOARD = "https://boards-api.greenhouse.io/v1/boards/{}"
# Words that appear in almost any company's PM/analyst openings: a title made only of these is weak evidence.
GENERIC_WORDS = frozenset(
    "product products analyst analytics associate manager management senior sr junior jr lead principal staff "
    "head i ii iii iv 1 2 3 founder founders s office chief of growth strategy business data pm apm and the a"
    .split())


def candidate_slugs(name: str) -> list[str]:
    words = normalize_company(name).split()
    if not words:
        return []
    slugs = ["".join(words), "-".join(words)]
    if len(words) > 1:
        slugs.append(words[0])
    return list(dict.fromkeys(slugs))


def _get(client: httpx.Client, url: str, sleep: Callable[[float], None], params: dict | None = None):
    """The JSON body, or None when there is no board at this URL (404)."""
    try:
        return get_json(client, url, params=params, retries=1, sleep=sleep)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise


def _board_titles(ats: str, data) -> list[str]:
    if ats == "lever":
        return [p.get("text", "") for p in data or [] if isinstance(p, dict)]
    return [j.get("title", "") for j in (data or {}).get("jobs", [])]


def _common_titles(board_titles: list[str], seen_titles: set[str]) -> set[str]:
    """The shared part of each board/job-site title pair that refers to the same opening."""
    common: set[str] = set()
    for title in board_titles:
        board = normalize_title(title)
        for seen in seen_titles:
            short, long_ = sorted((board, seen), key=len)
            if short and (short == long_ or (len(short.split()) >= 2 and short in long_)):
                common.add(short)
    return common


def _convincing(common: set[str], generic: frozenset[str]) -> bool:
    # Two different matching openings, or one with a specific word ("payments", "data platform").
    return len(common) >= 2 or any(set(c.split()) - generic for c in common)


def find_board(client: httpx.Client, name: str, seen_titles: set[str],
               sleep: Callable[[float], None] = time.sleep,
               generic: frozenset[str] = GENERIC_WORDS) -> tuple[str, str] | None:
    norm = normalize_company(name)
    slugs = candidate_slugs(name)
    full_name_slugs = set(slugs[:2])  # the bare first word ("zeta" for "Zeta Suite") needs the board's name
    for slug in slugs:
        for ats, url in BOARD_URLS.items():
            data = _get(client, url.format(slug), sleep, {"mode": "json"} if ats == "lever" else None)
            if data is None:
                continue
            if slug in full_name_slugs and _convincing(_common_titles(_board_titles(ats, data), seen_titles),
                                                       generic):
                return ats, slug
            if ats == "greenhouse":
                meta = _get(client, GREENHOUSE_BOARD.format(slug), sleep)
                if meta and normalize_company(meta.get("name", "")) == norm:
                    return ats, slug
    return None


def discover(conn: sqlite3.Connection, client: httpx.Client, seen: dict[str, tuple[str, set[str]]],
             skip: set[str], now: datetime, limit: int = MAX_PER_RUN,
             sleep: Callable[[float], None] = time.sleep, generic: frozenset[str] = GENERIC_WORDS) -> int:
    found = checked = 0
    for norm, (display, titles) in seen.items():
        if checked >= limit:
            break
        if not norm or norm in skip or not needs_check(conn, norm, now):
            continue
        checked += 1
        try:
            hit = find_board(client, display, titles, sleep, generic)
        except (httpx.HTTPError, ValueError):
            continue  # transient failure: leave unrecorded so the next run retries
        if hit:
            record_company(conn, norm, display, "active", hit[0], hit[1], now)
            found += 1
        else:
            record_company(conn, norm, display, "none", now=now)
    return found
