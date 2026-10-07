from __future__ import annotations

import re

import httpx

from jobseeker.contacts.people import Candidate

HUNTER_TO_KEY = {"{first}.{last}": "first.last", "{first}": "first", "{first}{last}": "firstlast",
                 "{f}{last}": "flast", "{f}.{last}": "f.last", "{first}_{last}": "first_last",
                 "{first}{l}": "firstl", "{last}.{first}": "last.first"}


def _profile_url(url: str) -> str | None:
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url or "")
    return f"https://www.linkedin.com/in/{m.group(1)}" if m else None


def _first_email(raw) -> str | None:
    for item in raw or []:
        if isinstance(item, str) and "@" in item:
            return item
        if isinstance(item, dict):
            value = item.get("email") or item.get("address") or item.get("value")
            if value and "@" in str(value):
                return str(value)
    return None


class ApifyClient:
    URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    SEARCH_ACTOR = "harvestapi~linkedin-profile-search"
    PROFILE_ACTOR = "harvestapi~linkedin-profile-scraper"
    SEARCH_PAGE_USD = 0.10
    PROFILE_EMAIL_USD = 0.01

    def __init__(self, token: str, client: httpx.Client | None = None):
        self.token = token
        self.client = client or httpx.Client(timeout=180)

    def _run(self, actor: str, payload: dict) -> list[dict]:
        resp = self.client.post(self.URL.format(actor=actor), params={"token": self.token, "timeout": 150},
                                json=payload)
        resp.raise_for_status()
        return resp.json()

    def search_people(self, company: str, words: str, location: str | None) -> list[Candidate]:
        payload = {"profileScraperMode": "Short", "currentCompanies": [company], "searchQuery": words,
                   "takePages": 1, "maxItems": 25}
        if location:
            payload["locations"] = [location]
        out = []
        for it in self._run(self.SEARCH_ACTOR, payload):
            name = f"{it.get('firstName') or ''} {it.get('lastName') or ''}".strip()
            url = _profile_url(it.get("linkedinUrl") or it.get("url") or "")
            if name and url:
                out.append(Candidate(name, it.get("headline") or "", url))
        return out

    def profile_email(self, linkedin_url: str) -> str | None:
        items = self._run(self.PROFILE_ACTOR, {"profileScraperMode": "Profile details + email search ($10 per 1k)",
                                               "queries": [linkedin_url]})
        for it in items:
            email = _first_email(it.get("emails"))
            if email:
                return email
        return None


class HunterClient:
    URL = "https://api.hunter.io/v2/domain-search"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=30)

    def domain_search(self, domain: str) -> dict:
        resp = self.client.get(self.URL, params={"domain": domain, "api_key": self.api_key, "limit": 10})
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        emails = [(e.get("first_name") or "", e.get("last_name") or "", e.get("value"))
                  for e in data.get("emails") or [] if e.get("value")]
        return {"pattern": HUNTER_TO_KEY.get(data.get("pattern") or ""), "emails": emails}
