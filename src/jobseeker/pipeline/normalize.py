from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser

from jobseeker.models import Job, RawJob

# Target cities first: canonical_city() returns the first match in this order.
CITY_ALIASES: dict[str, list[str]] = {
    "bengaluru": ["bengaluru", "bangalore", "blr"],
    "gurgaon": ["gurgaon", "gurugram"],
    "noida": ["noida", "greater noida"],
    "pune": ["pune"],
    "delhi": ["new delhi", "delhi"],
    "mumbai": ["mumbai", "bombay"],
    "hyderabad": ["hyderabad"],
    "chennai": ["chennai", "madras"],
    "kolkata": ["kolkata", "calcutta"],
}
_TITLE_ABBREV = [
    (r"\bsr\b\.?", "senior"), (r"\bjr\b\.?", "junior"), (r"\bapm\b", "associate product manager"),
    (r"\bpm\b", "product manager"), (r"\bmgr\b", "manager"), (r"\bassoc\b\.?", "associate"),
]
_COMPANY_STOP = {"pvt", "private", "ltd", "limited", "inc", "llp", "technologies", "technology", "india", "labs"}
_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "tr", "section"}
_HIDDEN_TAGS = {"script", "style", "noscript", "template"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in _HIDDEN_TAGS:
            self.hidden += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _HIDDEN_TAGS:
            self.hidden = max(0, self.hidden - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_to_text(s: str) -> str:
    if not s:
        return ""
    s = html.unescape(s)  # Greenhouse escapes the HTML once more
    parser = _TextExtractor()
    parser.feed(s)
    text = html.unescape("".join(parser.parts))
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def canonical_city(location: str) -> str | None:
    low = location.lower()
    for city, aliases in CITY_ALIASES.items():
        if any(re.search(rf"\b{re.escape(a)}\b", low) for a in aliases):
            return city
    return None


def normalize_title(title: str) -> str:
    t = title.lower()
    for pattern, repl in _TITLE_ABBREV:
        t = re.sub(pattern, repl, t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return " ".join(t.split())


def normalize_company(name: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return " ".join(t for t in tokens if t not in _COMPANY_STOP)


def fingerprint(company: str, title: str, city: str | None) -> str:
    key = f"{normalize_company(company)}|{normalize_title(title)}|{city or ''}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def normalize(raw: RawJob) -> Job:
    city = canonical_city(raw.location)
    is_remote = bool(raw.remote) or "remote" in raw.location.lower()
    return Job(
        **raw.model_dump(),
        location_city=city,
        is_remote=is_remote,
        fingerprint=fingerprint(raw.company, raw.title, city),
    )
