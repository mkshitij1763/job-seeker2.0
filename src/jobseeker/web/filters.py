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


def age(value: str | None, now: datetime | None = None) -> str:
    """Whole IST days since `value` ("today" on the same IST date)."""
    from jobseeker.clock import app_today

    if not value:
        return "?"
    dt = datetime.fromisoformat(value)
    days = (app_today(now) - app_today(dt if dt.tzinfo else dt.replace(tzinfo=UTC))).days
    return "today" if days <= 0 else f"{days}d"


def explain_stats(stats: dict, scored_today: int | None = None) -> list[dict]:
    """Header notes from run stats: the user's score share and the search plan's rotation. Neither needs action.
    scored_today is the day's usage (several runs a day); the run's own count is only a fallback."""
    user, fetch, notes = stats.get("user") or {}, stats.get("fetch") or {}, []
    why = user.get("stopped_by")
    if why == "share":
        n = scored_today if scored_today is not None else user.get("scored", 0)
        notes.append({"text": f"You've used today's {n} scores; more tomorrow", "action": False})
    elif why == "reserved":
        notes.append({"text": "Today's shared AI allowance is held for other users' first scores; yours resume tomorrow",
                      "action": False})
    elif why in ("global_cap", "quota"):
        notes.append({"text": "The shared AI limit ran out today; scoring resumes tomorrow", "action": False})
    if fetch.get("searches_trimmed"):  # counts are searches (items), not role and city pairs
        run = fetch.get("searches_run", 0)
        total = fetch.get("searches_total") or fetch.get("searches_planned", 0) + fetch["searches_trimmed"]
        notes.append({"text": f"Searched {run} of {total} searches; the other {total - run} rotate in over the next runs.",
                      "action": False})
    return notes


_OPENING_GREETING = re.compile(r"^\s*(hi|hello|hey|dear)\b[^,.!\n]{0,20}[,.!]\s*", re.I)


def personal_note(body: str, name: str) -> str:
    """LinkedIn connection note for one person: 'Hi <First>, ' in front, kept within LinkedIn's 300 characters."""
    from jobseeker.contacts.names import first_name_title

    first = first_name_title(name)
    body = body or ""
    if first:  # the draft's own "Hi," / "Hello there," would double up with ours
        body = _OPENING_GREETING.sub("", body, count=1)
    text = (f"Hi {first}, " if first else "") + body
    return text if len(text) <= 300 else text[:299] + "…"


_PER_ITEM = [(re.compile(r"^score job \d+: (\w+)"), "{n} job{s} couldn't be scored ({why}); retried next run"),
             (re.compile(r"^draft application \d+: (\w+)"), "{n} draft{s} couldn't be written ({why}); retried next run")]
_WHY = {"APIConnectionError": "connection error", "LLMError": "AI reply was unusable", "LLMUnavailable": "AI offline"}


def explain_run(errors: list[str]) -> list[dict]:
    """The last run's raw error strings as short plain-English notes; repeated per-job errors become one line.
    action=True marks the few that need the user (everything else fixes itself on the next run)."""
    notes: list[dict] = []
    grouped: dict[tuple[str, str], int] = {}
    for e in errors:
        for pattern, template in _PER_ITEM:
            m = pattern.match(e)
            if m:
                key = (template, _WHY.get(m.group(1), m.group(1)))
                grouped[key] = grouped.get(key, 0) + 1
                break
        else:
            notes.append(_explain_one(e))
    for (template, why), n in grouped.items():
        notes.append({"text": template.format(n=n, s="" if n == 1 else "s", why=why), "action": False})
    return notes


def _explain_one(e: str) -> dict:
    if e.startswith(("scoring stopped:", "drafting stopped:")):
        if "quota" in e:
            what = "scoring" if e.startswith("scoring") else "drafting"
            return {"text": f"Daily AI limit reached, so {what} paused; the rest happens in tomorrow's run",
                    "action": False}
        return {"text": "The AI service was unreachable, so scoring paused; it retries next run", "action": False}
    if m := re.match(r"linkedin descriptions: (\d+) failed", e):
        return {"text": f"LinkedIn didn't return {m.group(1)} job descriptions; retried tomorrow", "action": False}
    if m := re.match(r"(\w+): (\d+) of (\d+) searches returned no results", e):
        return {"text": f"{m.group(1).capitalize()} returned nothing for {m.group(2)} of {m.group(3)} searches "
                        "(probably rate-limited); usually fine by tomorrow", "action": False}
    if e.startswith("run aborted:"):
        return {"text": f"The run crashed ({e.removeprefix('run aborted: ')}). Ask Claude to look at it",
                "action": True}
    source, _, detail = e.partition(": ")
    return {"text": f"Couldn't fetch {source} ({detail[:80]}); retried next run" if detail else e, "action": False}
