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


def _titles_match(board_titles: list[str], seen_titles: set[str]) -> bool:
    for title in board_titles:
        board = normalize_title(title)
        for seen in seen_titles:
            short, long_ = sorted((board, seen), key=len)
            if short and (short == long_ or (len(short.split()) >= 2 and short in long_)):
                return True
    return False


def find_board(client: httpx.Client, name: str, seen_titles: set[str],
               sleep: Callable[[float], None] = time.sleep) -> tuple[str, str] | None:
    norm = normalize_company(name)
    for slug in candidate_slugs(name):
        for ats, url in BOARD_URLS.items():
            data = _get(client, url.format(slug), sleep, {"mode": "json"} if ats == "lever" else None)
            if data is None:
                continue
            if _titles_match(_board_titles(ats, data), seen_titles):
                return ats, slug
            if ats == "greenhouse":
                meta = _get(client, GREENHOUSE_BOARD.format(slug), sleep)
                if meta and normalize_company(meta.get("name", "")) == norm:
                    return ats, slug
    return None


def discover(conn: sqlite3.Connection, client: httpx.Client, seen: dict[str, tuple[str, set[str]]],
             skip: set[str], now: datetime, limit: int = MAX_PER_RUN,
             sleep: Callable[[float], None] = time.sleep) -> int:
    found = checked = 0
    for norm, (display, titles) in seen.items():
        if checked >= limit:
            break
        if not norm or norm in skip or not needs_check(conn, norm, now):
            continue
        checked += 1
        try:
            hit = find_board(client, display, titles, sleep)
        except (httpx.HTTPError, ValueError):
            continue  # transient failure: leave unrecorded so the next run retries
        if hit:
            record_company(conn, norm, display, "active", hit[0], hit[1], now)
            found += 1
        else:
            record_company(conn, norm, display, "none", now=now)
    return found
