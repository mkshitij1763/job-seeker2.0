from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta

from jobseeker.db.core import iso
from jobseeker.db.users import User, user_by_id

SESSION_DAYS = 30
REFRESH_AFTER = timedelta(hours=24)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at) VALUES (?,?,?,?,?)",
                 (_hash(token), user_id, iso(now), iso(now + timedelta(days=SESSION_DAYS)), iso(now)))
    conn.commit()
    return token


def user_for_token(conn: sqlite3.Connection, token: str, now: datetime) -> tuple[User, bool] | None:
    row = conn.execute("""SELECT s.token_hash, s.user_id, s.expires_at, s.last_seen_at, u.disabled_at
                          FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?""",
                       (_hash(token or ""),)).fetchone()
    if not row or row["expires_at"] <= iso(now) or row["disabled_at"]:
        return None
    refreshed = row["last_seen_at"] <= iso(now - REFRESH_AFTER)
    if refreshed:  # at most one write per session per day keeps reads lock-free
        conn.execute("UPDATE sessions SET expires_at = ?, last_seen_at = ? WHERE token_hash = ?",
                     (iso(now + timedelta(days=SESSION_DAYS)), iso(now), row["token_hash"]))
        conn.commit()
    return user_by_id(conn, row["user_id"]), refreshed


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token or ""),))
    conn.commit()


def delete_user_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()


def purge_expired(conn: sqlite3.Connection, now: datetime) -> int:
    cur = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso(now),))
    conn.commit()
    return cur.rowcount
