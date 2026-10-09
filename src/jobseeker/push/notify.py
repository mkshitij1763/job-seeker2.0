"""The daily "N new matches" alert. Called by run_all after each user's scoring; never raises."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

import httpx

from jobseeker.clock import app_day
from jobseeker.config import Settings
from jobseeker.db.core import iso
from jobseeker.push.send import InvalidSubscription, VapidKeys, send_one, vapid_from_settings

RUN_NOTE = "Couldn't send the match alert"
MAX_FAILURES = 5
log = logging.getLogger(__name__)

_LATEST = "s.id = (SELECT id FROM scores WHERE job_id = a.job_id AND user_id = a.user_id ORDER BY id DESC LIMIT 1)"


def _new_matches(conn: sqlite3.Connection, user_id: int, since: datetime) -> tuple[int, int]:
    row = conn.execute(
        f"""SELECT COUNT(*) AS n, MAX(s.score) AS top FROM applications a JOIN scores s ON {_LATEST}
            WHERE a.user_id = ? AND a.created_at >= ? AND s.recommendation = 'apply'""",
        (user_id, iso(since))).fetchone()
    return row["n"], row["top"] or 0


def _wants_alerts(conn: sqlite3.Connection, user_id: int) -> bool:
    row = conn.execute("SELECT data FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return json.loads(row["data"]).get("notify_new_matches", True) if row else True


def notify_new_matches(conn: sqlite3.Connection, user_id: int, run_started_at: datetime, now: datetime, *,
                       keys: VapidKeys | None = ..., client: httpx.Client | None = None) -> str | None:
    try:
        if keys is ...:
            keys = vapid_from_settings(Settings())
        today = app_day(now)
        user = conn.execute("SELECT notified_on FROM users WHERE id = ?", (user_id,)).fetchone()
        if keys is None or user is None or user["notified_on"] == today or not _wants_alerts(conn, user_id):
            return None
        n, top = _new_matches(conn, user_id, run_started_at)
        subs = conn.execute("SELECT * FROM push_subscriptions WHERE user_id = ?", (user_id,)).fetchall()
        if n == 0 or not subs:
            return None
        payload = {"title": "1 new match" if n == 1 else f"{n} new matches",
                   "body": f"Top: {top} · Open Job Seeker", "url": "/?band=apply"}
        own = client is None
        client = client or httpx.Client()
        delivered = 0
        try:
            for sub in subs:
                try:
                    status = send_one(client, sub["endpoint"], sub["p256dh"], sub["auth"], payload, keys, now)
                except InvalidSubscription as e:
                    log.warning("push subscription %s pruned: %s", sub["id"], e)
                    conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
                    continue
                except Exception as e:  # one device must never cost the others their alert
                    log.warning("push to %s failed: %s", sub["id"], e)
                    status = 0
                if 200 <= status < 300:
                    delivered += 1
                    conn.execute("UPDATE push_subscriptions SET last_success_at = ?, failures = 0 WHERE id = ?",
                                 (iso(now), sub["id"]))
                elif status in (404, 410) or sub["failures"] + 1 >= MAX_FAILURES:
                    conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
                else:
                    conn.execute("UPDATE push_subscriptions SET failures = failures + 1 WHERE id = ?", (sub["id"],))
            if delivered:
                conn.execute("UPDATE users SET notified_on = ? WHERE id = ?", (today, user_id))
            conn.commit()
        finally:
            if own:
                client.close()
        return None if delivered else RUN_NOTE
    except Exception:  # an alert must never fail the run
        log.exception("notify_new_matches failed for user %s", user_id)
        return RUN_NOTE
