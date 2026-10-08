from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from jobseeker.db.core import iso


def start_run(conn: sqlite3.Connection, now: datetime, user_id: int | None = None, kind: str = "legacy") -> int:
    cur = conn.execute("INSERT INTO runs (started_at, user_id, kind) VALUES (?, ?, ?)", (iso(now), user_id, kind))
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, stats: dict, errors: list[str], now: datetime) -> None:
    conn.execute("UPDATE runs SET finished_at=?, stats=?, errors=? WHERE id=?",
                 (iso(now), json.dumps(stats), json.dumps(errors), run_id))
    conn.commit()


def last_run(conn: sqlite3.Connection, user_id: int) -> dict | None:
    """The user's latest run, or a shared (user-less) one if that is newer."""
    row = conn.execute("SELECT * FROM runs WHERE user_id = ? OR user_id IS NULL ORDER BY id DESC LIMIT 1",
                       (user_id,)).fetchone()
    return dict(row) if row else None
