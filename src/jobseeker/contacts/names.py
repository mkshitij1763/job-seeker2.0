from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

PATTERNS: dict[str, str] = {
    "first.last": "{first}.{last}", "first": "{first}", "firstlast": "{first}{last}", "flast": "{f}{last}",
    "f.last": "{f}.{last}", "first_last": "{first}_{last}", "firstl": "{first}{l}", "last.first": "{last}.{first}",
}
DEFAULT_ORDER = list(PATTERNS)
_TITLES = {"dr", "mr", "mrs", "ms", "prof", "er", "ca", "cfa", "cpa", "pmp", "phd", "mba", "csm", "cspo"}
_ROLE_ADDRESSES = {"careers", "career", "jobs", "hr", "hiring", "recruit", "recruitment", "talent", "info",
                   "contact", "hello", "support", "help", "press", "media", "team", "admin", "sales", "noreply",
                   "no-reply", "privacy", "legal", "security", "partners", "marketing", "office"}


@dataclass(frozen=True)
class PersonName:
    first: str
    last: str
    initial_only: bool


def _words(raw: str) -> list[str]:
    s = re.split(r"[,|]", raw, maxsplit=1)[0]
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    words = [re.sub(r"[^a-z]", "", w.lower()) for w in s.split()]
    return [w for w in words if w and w not in _TITLES]


def clean_name(raw: str) -> PersonName | None:
    words = _words(raw)
    if not words:
        return None
    first = words[0]
    last = words[-1] if len(words) > 1 else ""
    if len(last) == 1:  # "Harsh M." hides the surname
        last = ""
    return PersonName(first=first, last=last, initial_only=len(first) == 1)


def first_name_title(raw: str) -> str:
    words = _words(raw)
    return words[0].capitalize() if words and len(words[0]) > 1 else ""


def _local(key: str, name: PersonName) -> str | None:
    tpl = PATTERNS[key]
    if ("{last}" in tpl or "{l}" in tpl) and not name.last:
        return None
    if name.initial_only and key not in ("flast", "f.last"):
        return None
    return tpl.format(first=name.first, last=name.last, f=name.first[0], l=name.last[:1])


def candidates(name: PersonName, domain: str, hints=()) -> list[str]:
    order = list(dict.fromkeys([h for h in hints if h in PATTERNS] + DEFAULT_ORDER))
    out = [f"{local}@{domain}" for key in order if (local := _local(key, name))]
    return list(dict.fromkeys(out))[:8]


def pattern_of(email: str, name: PersonName) -> str | None:
    local = email.split("@", 1)[0].lower()
    for key in DEFAULT_ORDER:
        if _local(key, name) == local:
            return key
    return None


def emails_in_text(text: str, domain: str) -> list[str]:
    found = re.findall(rf"[A-Za-z0-9._%+-]+@{re.escape(domain)}\b", text, re.I)
    return list(dict.fromkeys(e.lower() for e in found))


def infer_pattern(emails: list[str]) -> str | None:
    """Guess the company's pattern from public addresses (role addresses like careers@ are ignored)."""
    shapes: Counter = Counter()
    for e in emails:
        local = e.split("@", 1)[0].lower()
        if local in _ROLE_ADDRESSES or any(ch.isdigit() for ch in local):
            continue
        if re.fullmatch(r"[a-z]{2,}\.[a-z]{2,}", local):
            shapes["first.last"] += 1
        elif re.fullmatch(r"[a-z]\.[a-z]{2,}", local):
            shapes["f.last"] += 1
        elif re.fullmatch(r"[a-z]{2,}_[a-z]{2,}", local):
            shapes["first_last"] += 1
    return shapes.most_common(1)[0][0] if shapes else None
