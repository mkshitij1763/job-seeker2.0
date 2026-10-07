from __future__ import annotations

import re
from urllib.parse import urlparse

from jobseeker.pipeline.normalize import normalize_company

_SKIP_HOSTS = ("linkedin.", "naukri.", "indeed.", "glassdoor.", "lever.co", "greenhouse.io", "ashbyhq.com",
               "wellfound.", "instahyre.", "cutshort.", "facebook.", "twitter.", "x.com", "instagram.",
               "youtube.", "wikipedia.", "crunchbase.", "ambitionbox.", "zaubacorp.", "github.", "medium.",
               "google.", "apple.com", "bloomberg.", "gmail.", "yahoo.", "outlook.", "hotmail.")
_TWO_PART_TLDS = {"co.in", "co.uk", "com.au", "co.jp", "com.sg", "co.nz", "org.in", "net.in", "com.br"}


def _registrable(host: str) -> str:
    host = host.lower().strip(".")
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_PART_TLDS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _skip(host: str) -> bool:
    return any(s in host for s in _SKIP_HOSTS)


def _pick(hosts: list[str], company: str) -> str | None:
    token = (normalize_company(company).split() or [""])[0]
    domains = [_registrable(h) for h in hosts if h and not _skip(h)]
    for d in domains:
        if token and token in d.split(".")[0]:
            return d
    return domains[0] if domains else None


def domain_from_text(text: str, company: str) -> str | None:
    hosts = re.findall(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", text)
    hosts += [urlparse(u).hostname or "" for u in re.findall(r"https?://[^\s)>\]]+", text)]
    token = (normalize_company(company).split() or [""])[0]
    picked = _pick(hosts, company)
    return picked if picked and token and token in picked.split(".")[0] else None


def official_domain(results: list[dict], company: str) -> str | None:
    return _pick([urlparse(r.get("url", "")).hostname or "" for r in results], company)


def mx_host(domain: str) -> str | None:
    import dns.exception
    import dns.resolver

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
    except (dns.exception.DNSException, OSError):
        return None
    best = sorted(answers, key=lambda r: r.preference)
    return str(best[0].exchange).rstrip(".") if best else None
