"""Presentation helpers for the templates: pure functions, plus nav_counts' read-only queries."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from jobseeker.config import Rubric

TIER_LABELS = {"strong": "Strong match", "good": "Good match", "weak": "Weak match", "none": "Not scored"}
FACTOR_LABELS = {"role_fit": "Role fit", "experience_fit": "Experience", "skills_match": "Skills",
                 "company": "Company", "location_pay": "Location & pay"}
STEPS = ["Find contacts", "Approve", "Send in Gmail", "Mark sent"]
_DONE = {"sent", "replied", "interview", "offer"}


def tier(score: int | None) -> str:
    if score is None:
        return "none"
    return "strong" if score >= 90 else "good" if score >= 70 else "weak"


def factor_bars(breakdown: str | dict | None, rubric: Rubric) -> list[dict]:
    """One bar per rubric dimension present in the score, in rubric order, clamped to that dimension's max."""
    if isinstance(breakdown, str):
        try:
            breakdown = json.loads(breakdown)
        except ValueError:
            return []
    values = breakdown if isinstance(breakdown, dict) else {}
    bars = []
    for d in rubric.dimensions:
        try:
            raw = int(values[d.key])
        except (KeyError, TypeError, ValueError):
            continue
        if d.max <= 0:
            continue
        v = max(0, min(raw, d.max))
        bars.append({"key": d.key, "label": FACTOR_LABELS.get(d.key, d.key.replace("_", " ").capitalize()),
                     "value": v, "max": d.max, "pct": round(100 * v / d.max)})
    return bars


def next_step(status: str, has_people: bool) -> int | None:
    """1-4 is the current step of Find contacts -> Approve -> Send in Gmail -> Mark sent; 5 = all done;
    None = this status isn't on that path (new, skipped, snoozed, ...)."""
    if status == "drafted":
        return 2 if has_people else 1
    if status == "approved":
        return 3
    return 5 if status in _DONE else None


def _words(value) -> str:
    return str(value or "").replace("_", " ")


def timeline(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        try:
            p = json.loads(e.get("payload") or "{}")
        except ValueError:
            p = {}
        p = p if isinstance(p, dict) else {}
        kind = e.get("type") or ""
        if kind == "status":
            text = f"Marked {_words(p.get('to')) or '?'}" + (f" ({p['reason']})" if p.get("reason") else "")
        elif kind == "undo":
            text = f"Undid {_words(p.get('from'))}, back to {_words(p.get('to'))}"
        elif kind == "followup":
            text = f"Follow-up {p['n']} recorded" if p.get("n") else "Follow-up recorded"
        elif kind == "contact":
            text = "Contact saved"
        else:
            text = _words(kind).capitalize()
        dt = datetime.fromisoformat(e["at"])
        out.append({"day": f"{dt.day} {dt:%b}", "text": text})
    return out


def nav_counts(conn: sqlite3.Connection) -> dict:
    """Badges for the sidebar/tab bar: Jobs = default inbox rows, Pipeline = applications after Approve,
    Today = Gmail drafts waiting to be sent."""
    from jobseeker.db.queries import inbox

    pipeline = conn.execute("""SELECT COUNT(*) FROM applications
                               WHERE status IN ('approved', 'sent', 'replied', 'interview')""").fetchone()[0]
    ready = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'approved'").fetchone()[0]
    return {"jobs": len(inbox(conn)), "pipeline": pipeline, "today": ready}
