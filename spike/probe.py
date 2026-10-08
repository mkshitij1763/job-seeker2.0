"""THROWAWAY hosting-feasibility probe. Not product code; lives only on branch spike/hosting."""
from __future__ import annotations

import json
import socket
import time
import traceback

import httpx

from jobseeker.config import Company, SearchConfig
from jobseeker.sources.ashby import AshbySource
from jobseeker.sources.greenhouse import GreenhouseSource
from jobseeker.sources.http import make_client
from jobseeker.sources.jobspy_source import JobSpySource, fetch_description
from jobseeker.sources.lever import LeverSource

results: dict[str, str] = {}


def ip_info() -> str:
    try:
        d = httpx.get("https://ipinfo.io/json", timeout=10).json()
        return f"{d.get('org')} {d.get('city')},{d.get('country')}"
    except Exception as e:
        return f"unknown ({e})"


def jobspy(site: str):
    search = SearchConfig(queries=["Product Analyst"], locations=["Bengaluru"], remote_query=False,
                          results_per_search=20, hours_old=72, sites=[site])
    src = JobSpySource(site, search, sleep=lambda s: None)
    t = time.time()
    try:
        jobs = src.fetch(None)
        warn = f" warnings={src.warnings}" if src.warnings else ""
        with_jd = sum(1 for j in jobs if j.jd_text)
        results[site] = f"{len(jobs)} jobs ({with_jd} with JD) in {time.time() - t:.0f}s{warn}"
        return jobs
    except Exception as e:
        results[site] = f"ERROR {type(e).__name__}: {str(e)[:200]}"
        return []


def ats():
    companies = [Company(name="Groww", ats="greenhouse", slug="groww"),
                 Company(name="Databricks", ats="greenhouse", slug="databricks"),
                 Company(name="CRED", ats="lever", slug="cred"),
                 Company(name="Meesho", ats="lever", slug="meesho"),
                 Company(name="Sarvam AI", ats="ashby", slug="sarvam")]
    kinds = {"greenhouse": GreenhouseSource, "lever": LeverSource, "ashby": AshbySource}
    with make_client() as client:
        for c in companies:
            try:
                results[f"{c.ats}:{c.slug}"] = f"{len(kinds[c.ats](c).fetch(client))} jobs"
            except Exception as e:
                results[f"{c.ats}:{c.slug}"] = f"ERROR {type(e).__name__}: {str(e)[:200]}"


def smtp(host: str):
    """Connect + EHLO + QUIT only. Never MAIL FROM / RCPT / DATA."""
    try:
        with socket.create_connection((host, 25), timeout=15) as s:
            f = s.makefile("rb")
            banner = f.readline().decode(errors="replace").strip()
            s.sendall(b"EHLO probe.example.com\r\n")
            ehlo = f.readline().decode(errors="replace").strip()
            s.sendall(b"QUIT\r\n")
        results[f"smtp25:{host}"] = f"OPEN banner={banner[:80]!r} ehlo={ehlo[:60]!r}"
    except Exception as e:
        results[f"smtp25:{host}"] = f"BLOCKED/FAILED {type(e).__name__}: {e}"


def main():
    results["network"] = ip_info()
    li = jobspy("linkedin")
    jobspy("naukri")
    jobspy("indeed")
    ok = 0
    for j in li[:3]:
        try:
            ok += bool(fetch_description("linkedin", j.source_job_id))
        except Exception as e:
            results["linkedin_desc_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    results["linkedin_descriptions"] = f"{ok}/{min(3, len(li))} fetched" if li else "skipped (no LinkedIn jobs)"
    ats()
    smtp("gmail-smtp-in.l.google.com")
    smtp("sliceit-com.mail.protection.outlook.com")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
    print("SPIKE_RESULTS " + json.dumps(results, indent=2))
