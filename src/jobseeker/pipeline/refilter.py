from __future__ import annotations

import sqlite3
from datetime import datetime

from jobseeker.config import Preferences
from jobseeker.db.applications import blocked_companies, get_status, transition
from jobseeker.db.jobs import job_from_row, set_filter_reason
from jobseeker.pipeline.prefilter import prefilter

BEFORE_OUTREACH = {"new", "shortlisted", "drafted"}  # from "approved" on, a Gmail draft exists


def refilter(conn: sqlite3.Connection, user_id: int, prefs: Preferences, now: datetime, apply: bool) -> list[dict]:
    """Re-apply today's prefilter rules to stored, unfiltered jobs (rules otherwise apply only at insert).

    Age is not re-judged: old jobs already expire on their own. Applications not yet approved are skipped
    (undoable); later ones keep their status.
    """
    blocked = blocked_companies(conn, user_id)
    rows = conn.execute("""SELECT j.*, a.id AS app_id FROM jobs j
                           LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = :u
                           LEFT JOIN applications a ON a.job_id = j.id AND a.user_id = :u
                           WHERE uj.filter_reason IS NULL ORDER BY j.id""", {"u": user_id}).fetchall()
    changes = []
    for row in rows:
        row = dict(row)
        reason = prefilter(job_from_row(row), prefs, now, blocked)
        if not reason or reason.startswith("stale:"):
            continue
        status = get_status(conn, row["app_id"]) if row["app_id"] else None
        change = {"job_id": row["id"], "app_id": row["app_id"], "title": row["title"], "company": row["company"],
                  "reason": reason, "status": status, "skips": status in BEFORE_OUTREACH}
        changes.append(change)
        if apply:
            set_filter_reason(conn, user_id, row["id"], reason)
            if change["skips"]:
                transition(conn, row["app_id"], "skipped", {"reason": f"refilter: {reason}"}, now)
    return changes
