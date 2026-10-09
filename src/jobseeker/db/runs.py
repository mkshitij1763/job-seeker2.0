from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from jobseeker.db.core import iso


def start_run(conn: sqlite3.Connection, now: datetime, user_id: int | None = None, kind: str = "legacy",
              trigger: str = "cli", parent_id: int | None = None) -> int:
    cur = conn.execute("INSERT INTO runs (started_at, user_id, kind, trigger, parent_id) VALUES (?, ?, ?, ?, ?)",
                       (iso(now), user_id, kind, trigger, parent_id))
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


def header_run(conn: sqlite3.Connection, user_id: int) -> tuple[dict | None, list[str], dict]:
    """The header's run notes: the user's latest run plus its fetch run's errors; before any, the latest fetch
    (or a pre-run_all 'legacy' run of theirs or a shared one, so the notes don't vanish across the upgrade)."""
    row = conn.execute("SELECT * FROM runs WHERE kind = 'user' AND user_id = ? ORDER BY id DESC LIMIT 1",
                       (user_id,)).fetchone()
    parent = None
    if row and row["parent_id"]:
        parent = conn.execute("SELECT * FROM runs WHERE id = ?", (row["parent_id"],)).fetchone()
    if row is None:
        row = parent = conn.execute(
            """SELECT * FROM runs WHERE kind = 'fetch' OR (kind = 'legacy' AND (user_id = ? OR user_id IS NULL))
               ORDER BY id DESC LIMIT 1""", (user_id,)).fetchone()
        if row is None:
            return None, [], {"user": {}, "fetch": {}}
        return dict(row), json.loads(row["errors"]), {"user": {}, "fetch": json.loads(row["stats"])}
    errors = json.loads(row["errors"]) + (json.loads(parent["errors"]) if parent else [])
    return dict(row), errors, {"user": json.loads(row["stats"]), "fetch": json.loads(parent["stats"]) if parent else {}}
