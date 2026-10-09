"""Is outbound port 25 usable from this server? Asked at most once a day (Oracle and most clouds block it)."""
from __future__ import annotations

import socket
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

from jobseeker.db.core import iso

PROBE_TTL = timedelta(hours=24)
PROBE_HOST = "gmail-smtp-in.l.google.com"


def _probe() -> bool:
    try:
        with socket.create_connection((PROBE_HOST, 25), timeout=5):
            return True
    except OSError:
        return False


def port25_open(conn: sqlite3.Connection, now: datetime, probe: Callable[[], bool] = _probe) -> bool:
    row = conn.execute("SELECT value, checked_at FROM app_state WHERE key = 'smtp25'").fetchone()
    if row and row["checked_at"] >= iso(now - PROBE_TTL):
        return row["value"] == "open"
    is_open = probe()
    conn.execute("""INSERT INTO app_state (key, value, checked_at) VALUES ('smtp25', ?, ?)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value, checked_at = excluded.checked_at""",
                 ("open" if is_open else "blocked", iso(now)))
    conn.commit()
    return is_open
