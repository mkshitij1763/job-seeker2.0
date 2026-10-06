from __future__ import annotations

import time
from collections.abc import Callable

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


def make_client() -> httpx.Client:
    return httpx.Client(timeout=20.0, follow_redirects=True,
                        headers={"User-Agent": "jobseeker/0.1 (personal job search)"})


def get_json(client: httpx.Client, url: str, *, params: dict | None = None, headers: dict | None = None,
             retries: int = 3, sleep: Callable[[float], None] = time.sleep):
    for attempt in range(retries + 1):
        try:
            resp = client.get(url, params=params, headers=headers)
        except httpx.TransportError:
            if attempt == retries:
                raise
            sleep(2 ** attempt)
            continue
        if resp.status_code in RETRY_STATUS and attempt < retries:
            sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("unreachable")
