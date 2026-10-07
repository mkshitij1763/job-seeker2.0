from __future__ import annotations

import httpx


class TavilyClient:
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=30)

    def search(self, query: str, include_domains: list[str] | None = None, max_results: int = 10) -> list[dict]:
        body: dict = {"query": query, "max_results": max_results, "search_depth": "basic"}
        if include_domains:
            body["include_domains"] = include_domains
        resp = self.client.post(self.URL, json=body, headers={"Authorization": f"Bearer {self.api_key}"})
        resp.raise_for_status()
        return resp.json().get("results", [])
