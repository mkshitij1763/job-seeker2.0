from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from jobseeker.db.core import iso


def start_run(conn: sqlite3.Connection, now: datetime) -> int:
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (iso(now),))
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, stats: dict, errors: list[str], now: datetime) -> None:
    conn.execute("UPDATE runs SET finished_at=?, stats=?, errors=? WHERE id=?",
                 (iso(now), json.dumps(stats), json.dumps(errors), run_id))
    conn.commit()


def last_run(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
