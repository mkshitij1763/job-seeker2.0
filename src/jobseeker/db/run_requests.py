"""Fetch-now requests: queued by the web, run by the next tick."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from jobseeker.clock import app_today, day_start_utc
from jobseeker.db.core import iso

# A run the app itself cut short (a deploy or a variables change SIGTERMs the tick). Written into the runs' errors, it
# frees the user's Fetch now: such runs count toward neither the per-user spacing nor the daily cap.
INTERRUPTED = "Interrupted by an app update; try again"
_NOT_INTERRUPTED = "errors NOT LIKE '%' || ? || '%'"


def queue(conn: sqlite3.Connection, user_id: int, now: datetime, trigger: str = "fetch_now") -> int:
    """trigger 'onboarding' is the new user's first scoring run: no fetch, exempt from Fetch now's spacing and cap."""
    cur = conn.execute("INSERT INTO run_requests (user_id, requested_at, status, trigger) VALUES (?, ?, 'queued', ?)",
                       (user_id, iso(now), trigger))
    conn.commit()
    return cur.lastrowid


def next_queued(conn) -> dict | None:
    row = conn.execute("SELECT * FROM run_requests WHERE status = 'queued' ORDER BY requested_at, id LIMIT 1").fetchone()
    return dict(row) if row else None


def pending(conn, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM run_requests WHERE user_id = ? AND status IN ('queued', 'running') "
                       "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return dict(row) if row else None


def mark(conn, req_id: int, status: str, now: datetime, run_id: int | None = None) -> None:
    done = iso(now) if status in ("done", "failed") else None
    conn.execute("UPDATE run_requests SET status = ?, run_id = COALESCE(?, run_id), finished_at = ? WHERE id = ?",
                 (status, run_id, done, req_id))
    conn.commit()


def fail_stuck(conn, now: datetime, minutes: int) -> int:
    """A 'running' request whose run died (no live lock holder) is closed as failed after the takeover window."""
    cur = conn.execute("UPDATE run_requests SET status = 'failed', finished_at = ? WHERE status = 'running' "
                       "AND requested_at < ?", (iso(now), iso(now - timedelta(minutes=minutes))))
    conn.commit()
    return cur.rowcount


def last_fetch_now_started(conn, user_id: int) -> str | None:
    row = conn.execute("SELECT MAX(started_at) FROM runs WHERE kind = 'user' AND trigger = 'fetch_now' AND user_id = ? "
                       f"AND {_NOT_INTERRUPTED}", (user_id, INTERRUPTED)).fetchone()
    return row[0]


def interrupted_since(conn, user_id: int, since: datetime) -> bool:
    """The user's latest request failed because the app interrupted its run, after `since`."""
    row = conn.execute("""SELECT r.errors FROM run_requests q JOIN runs r ON r.id = q.run_id
                          WHERE q.user_id = ? AND q.status = 'failed' AND q.finished_at >= ?
                            AND q.id = (SELECT MAX(id) FROM run_requests WHERE user_id = ?)""",
                       (user_id, iso(since), user_id)).fetchone()
    return bool(row) and INTERRUPTED in row["errors"]


def fetch_now_count_today(conn, now: datetime, *, include_queued: bool = True) -> int:
    """Fetch now runs started today, plus requests still queued (each will start one). The tick re-checks with
    include_queued=False just before running a request, so the queue can never push the day past the cap."""
    started = conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'fetch' AND trigger = 'fetch_now' AND started_at >= ? "
                           f"AND {_NOT_INTERRUPTED}", (iso(day_start_utc(app_today(now))), INTERRUPTED)).fetchone()[0]
    if not include_queued:
        return started
    return started + conn.execute("SELECT COUNT(*) FROM run_requests WHERE status = 'queued' "
                                  "AND trigger = 'fetch_now'").fetchone()[0]
