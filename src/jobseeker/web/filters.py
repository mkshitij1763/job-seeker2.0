from __future__ import annotations

import re
from datetime import UTC, datetime

from markupsafe import Markup, escape


def highlight(text: str, terms: list[str]) -> Markup:
    safe = str(escape(text or ""))
    words = sorted({t for t in terms if t and len(t) > 1}, key=len, reverse=True)
    if words:
        pattern = re.compile("|".join(re.escape(str(escape(w))) for w in words), re.I)
        safe = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", safe)
    return Markup(safe.replace("\n", "<br>"))


def age(value: str | None) -> str:
    if not value:
        return "?"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - dt).days
    return "today" if days <= 0 else f"{days}d"


def personal_note(body: str, name: str) -> str:
    """LinkedIn connection note for one person: 'Hi <First>, ' in front, kept within LinkedIn's 300 characters."""
    from jobseeker.contacts.names import first_name_title

    first = first_name_title(name)
    head = f"Hi {first}, " if first else ""
    text = head + (body or "")
    return text if len(text) <= 300 else text[:299] + "…"
