"""One run at a time across processes: a row with a heartbeat; a silent holder is taken over after N minutes."""
from __future__ import annotations

import os
import socket
import sqlite3
from datetime import datetime, timedelta

from jobseeker.db.core import iso


class LockLost(RuntimeError):
    pass


def holder_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire(conn: sqlite3.Connection, name: str, holder: str, now: datetime, takeover_minutes: int) -> bool:
    cur = conn.execute(
        """INSERT INTO locks (name, holder, acquired_at, heartbeat_at) VALUES (?, ?, ?, ?)
           ON CONFLICT (name) DO UPDATE SET holder = excluded.holder, acquired_at = excluded.acquired_at,
             heartbeat_at = excluded.heartbeat_at
           WHERE locks.heartbeat_at < ?""",
        (name, holder, iso(now), iso(now), iso(now - timedelta(minutes=takeover_minutes))))
    conn.commit()
    return cur.rowcount == 1


def heartbeat(conn: sqlite3.Connection, name: str, holder: str, now: datetime) -> None:
    cur = conn.execute("UPDATE locks SET heartbeat_at = ? WHERE name = ? AND holder = ?", (iso(now), name, holder))
    conn.commit()
    if cur.rowcount != 1:
        raise LockLost(f"lock {name!r} was taken over")


def release(conn: sqlite3.Connection, name: str, holder: str) -> None:
    conn.execute("DELETE FROM locks WHERE name = ? AND holder = ?", (name, holder))
    conn.commit()


def held_since(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT acquired_at FROM locks WHERE name = ?", (name,)).fetchone()
    return row["acquired_at"] if row else None
