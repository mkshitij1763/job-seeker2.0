"""Probe ATS boards before adding them to companies.yaml.

Usage: uv run python scripts/verify_companies.py swiggy zepto razorpay
Prints a ready-to-paste YAML line for every slug that has a live board with jobs.
"""
import sys

import httpx

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{}/jobs",
    "lever": "https://api.lever.co/v0/postings/{}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{}",
}
CITIES = ("bengaluru", "bangalore", "gurgaon", "gurugram", "noida", "pune")


def main(slugs: list[str]) -> None:
    with httpx.Client(timeout=15) as client:
        for slug in slugs:
            for ats, url in URLS.items():
                try:
                    r = client.get(url.format(slug))
                except httpx.HTTPError:
                    continue
                if r.status_code != 200:
                    continue
                data = r.json()
                jobs = data if isinstance(data, list) else data.get("jobs", [])
                if not jobs:
                    continue
                hits = sum(str(jobs).lower().count(c) for c in CITIES)
                print(f"  - {{name: {slug.title()}, ats: {ats}, slug: {slug}, tier: 2}}"
                      f"   # {len(jobs)} jobs, {hits} target-city mentions")


if __name__ == "__main__":
    main(sys.argv[1:])
