from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from jobseeker.db.applications import get_application, get_drafts, get_events
from jobseeker.db.core import iso
from jobseeker.db.jobs import get_job, latest_score

_LATEST_SCORE = "s.id = (SELECT id FROM scores WHERE job_id = j.id AND user_id = a.user_id ORDER BY id DESC LIMIT 1)"
_INBOX_STATUSES = ("new", "shortlisted", "drafted")
PIPELINE_COLUMNS = ["shortlisted", "drafted", "approved", "sent", "replied", "interview",
                    "applied_via_portal", "offer", "rejected"]


def inbox(conn: sqlite3.Connection, user_id: int, band: str = "apply", family: str | None = None, city: str | None = None,
          source: str | None = None, status: str | None = None) -> list[dict]:
    sql = f"""SELECT a.id AS app_id, a.status, j.id AS job_id, j.title, j.company, j.location, j.location_city,
                     j.remote, j.posted_at, j.first_seen_at, j.source, s.score, s.matches, s.gaps,
                     s.role_family, s.recommendation,
                     (SELECT COUNT(*) FROM application_contacts ac WHERE ac.application_id = a.id) AS people
              FROM applications a JOIN jobs j ON j.id = a.job_id JOIN scores s ON {_LATEST_SCORE}
              WHERE a.user_id = ?"""
    params: list = [user_id]
    if band in ("apply", "review", "hide"):
        sql += " AND s.recommendation = ?"
        params.append(band)
    if status:
        sql += " AND a.status = ?"
        params.append(status)
    else:
        sql += f" AND a.status IN ({','.join('?' * len(_INBOX_STATUSES))})"
        params += list(_INBOX_STATUSES)
    for col, val in (("s.role_family", family), ("j.location_city", city), ("j.source", source)):
        if val:
            sql += f" AND {col} = ?"
            params.append(val)
    sql += " ORDER BY s.score DESC, j.first_seen_at DESC LIMIT 300"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def inbox_facets(conn: sqlite3.Connection, user_id: int) -> dict:
    def distinct(sql, params=()):
        return [r[0] for r in conn.execute(sql, params).fetchall() if r[0]]
    return {
        "families": distinct("SELECT DISTINCT role_family FROM scores WHERE user_id = ? ORDER BY 1", (user_id,)),
        "cities": distinct("SELECT DISTINCT location_city FROM jobs ORDER BY 1"),
        "sources": distinct("SELECT DISTINCT source FROM jobs ORDER BY 1"),
    }


def application_detail(conn: sqlite3.Connection, user_id: int, app_id: int) -> dict | None:
    app = get_application(conn, app_id)
    if not app or app["user_id"] != user_id:
        return None
    contact = None
    if app["contact_id"]:
        row = conn.execute("SELECT * FROM contacts WHERE id = ?", (app["contact_id"],)).fetchone()
        contact = dict(row) if row else None
    return {
        "app": app, "job": get_job(conn, app["job_id"]), "score": latest_score(conn, user_id, app["job_id"]),
        "contact": contact, "drafts": get_drafts(conn, app_id), "events": get_events(conn, app_id),
        "warnings": json.loads(app["draft_warnings"]),
    }


def pipeline(conn: sqlite3.Connection, user_id: int, now: datetime) -> dict[str, list[dict]]:
    rows = conn.execute(
        f"""SELECT a.id AS app_id, a.status, a.followups_sent, j.title, j.company, s.score,
                   (SELECT COUNT(*) FROM application_contacts ac WHERE ac.application_id = a.id) AS people,
                   (SELECT at FROM events e WHERE e.application_id = a.id ORDER BY e.id DESC LIMIT 1) AS last_at
            FROM applications a JOIN jobs j ON j.id = a.job_id JOIN scores s ON {_LATEST_SCORE}
            WHERE a.user_id = ? AND a.status IN ({','.join('?' * len(PIPELINE_COLUMNS))})
            ORDER BY s.score DESC""", [user_id, *PIPELINE_COLUMNS]).fetchall()
    board: dict[str, list[dict]] = {c: [] for c in PIPELINE_COLUMNS}
    for r in rows:
        card = dict(r)
        last = datetime.fromisoformat(card["last_at"]) if card["last_at"] else now
        card["days_since"] = max(0, (now - last).days)
        card["needs_followup"] = card["status"] == "sent" and card["days_since"] >= 5 and card["followups_sent"] < 2
        card["third"] = None
        if card["needs_followup"]:
            t = conn.execute(
                """SELECT c.name, ac.label FROM application_contacts ac JOIN contacts c ON c.id = ac.contact_id
                   WHERE ac.application_id = ? AND ac.rank = 3 AND ac.emailed_at IS NULL
                   AND c.email != '' AND c.email_status != 'bounced'""", (card["app_id"],)).fetchone()
            if t:
                card["third"] = {"name": t["name"], "label": t["label"]}
        board[card["status"]].append(card)
    return board


def stats(conn: sqlite3.Connection, user_id: int, now: datetime, days: int = 30) -> dict:
    since = iso(now - timedelta(days=days))

    def moved_to(status: str) -> int:
        return conn.execute(  # a move later undone (e.g. "Mark sent" by mistake) doesn't count
            """SELECT COUNT(DISTINCT e.application_id) FROM events e JOIN applications a ON a.id = e.application_id
               WHERE a.user_id = ? AND e.type = 'status' AND json_extract(e.payload, '$.to') = ? AND e.at >= ?
               AND NOT EXISTS (SELECT 1 FROM events u WHERE u.application_id = e.application_id
                               AND u.type = 'undo' AND u.id > e.id AND json_extract(u.payload, '$.from') = ?)""",
            (user_id, status, since, status)).fetchone()[0]

    sent, replied = moved_to("sent"), moved_to("replied")
    per_source = {r["source"]: r["n"] for r in conn.execute(
        "SELECT source, COUNT(*) AS n FROM jobs WHERE first_seen_at >= ? GROUP BY source ORDER BY n DESC",
        (since,)).fetchall()}
    return {"drafted": moved_to("drafted"), "sent": sent, "replied": replied,
            "reply_rate": (replied / sent) if sent else 0.0, "interviews": moved_to("interview"),
            "jobs_per_source": per_source}


def today(conn: sqlite3.Connection, user_id: int, now: datetime) -> dict:
    """What needs the user now, most urgent first: Gmail drafts to send, follow-ups due, drafts ready to approve,
    drafted jobs that still need people."""
    from jobseeker.db.contacts_repo import nudge_due, third_due

    rows = [dict(r) for r in conn.execute(
        f"""SELECT a.id AS app_id, a.status, j.title, j.company, j.first_seen_at, s.score,
                   (SELECT COUNT(*) FROM application_contacts ac WHERE ac.application_id = a.id) AS people
            FROM applications a JOIN jobs j ON j.id = a.job_id JOIN scores s ON {_LATEST_SCORE}
            WHERE a.user_id = ? AND a.status IN ('new', 'shortlisted', 'drafted', 'approved', 'sent')
            ORDER BY s.score DESC, a.id""", (user_id,)).fetchall()]
    drafted = [r for r in rows if r["status"] == "drafted"]
    since = iso(now - timedelta(days=1))
    return {
        "send": [r for r in rows if r["status"] == "approved"],
        "followups": [r for r in rows if r["status"] == "sent"
                      and (nudge_due(conn, r["app_id"], now) or third_due(conn, r["app_id"], now))],
        "ready": [r for r in drafted if r["people"]],
        "find_contacts": [r for r in drafted if not r["people"]],
        "shortlisted": [r for r in rows if r["status"] == "shortlisted"],  # the matching-only path
        "new_since_yesterday": sum(1 for r in rows if r["status"] in _INBOX_STATUSES and r["first_seen_at"] >= since),
    }
