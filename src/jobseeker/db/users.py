from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from jobseeker.db.core import iso

OWNER_ID = 1


def ensure_owner(conn: sqlite3.Connection, email: str) -> None:
    """Give user 1 the OWNER_EMAIL until they first sign in (after that, their Google identity is fixed)."""
    if email.strip():
        conn.execute("UPDATE users SET email = lower(?) WHERE id = ? AND google_sub IS NULL", (email.strip(), OWNER_ID))
        conn.commit()


FALLBACK_OWNER = "the person who shared this link"


class EmailLinkedElsewhere(ValueError):
    """An invited email whose account is already bound to a different Google `sub` (e.g. a re-created account)."""


class LastAdmin(ValueError):
    pass


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    is_admin: bool
    google_sub: str | None
    outreach_enabled: bool = False


def _user(row) -> User:
    return User(row["id"], row["email"], row["name"], bool(row["is_admin"]), row["google_sub"],
                bool(row["outreach_enabled"]))


def user_by_id(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user(row) if row else None


def resolve_sign_in(conn: sqlite3.Connection, sub: str, email: str, name: str, now: datetime) -> User | None:
    """A verified Google identity → its user, or None (not invited, or disabled). Identity is `sub` after the first
    sign-in, so a changed Gmail address can't take over an account."""
    email = email.strip().lower()
    row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM users WHERE email = ? AND google_sub IS NULL", (email,)).fetchone()
        if row is not None:
            conn.execute("UPDATE users SET google_sub = ? WHERE id = ?", (sub, row["id"]))
    if row is None:
        if not conn.execute("SELECT 1 FROM invites WHERE email = ?", (email,)).fetchone():
            return None
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise EmailLinkedElsewhere(email)
        cur = conn.execute("INSERT INTO users (google_sub, email, name, created_at) VALUES (?, ?, ?, ?)",
                           (sub, email, name, iso(now)))
        conn.execute("UPDATE invites SET accepted_at = ? WHERE email = ?", (iso(now), email))
        conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, updated_at)
                        VALUES (?, '{}', 1, 'roles', ?)""", (cur.lastrowid, iso(now)))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    if row["disabled_at"]:
        conn.commit()
        return None
    conn.execute("UPDATE users SET last_login_at = ?, name = ? WHERE id = ?",
                 (iso(now), name or row["name"], row["id"]))
    conn.commit()
    return user_by_id(conn, row["id"])


def owner_first_name(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT name FROM users WHERE id = ?", (OWNER_ID,)).fetchone()
    first = (row["name"] if row else "").split()
    return first[0] if first else FALLBACK_OWNER


def add_invite(conn: sqlite3.Connection, email: str, invited_by: int, now: datetime) -> None:
    conn.execute("INSERT OR IGNORE INTO invites (email, invited_by, created_at) VALUES (lower(?), ?, ?)",
                 (email.strip(), invited_by, iso(now)))
    conn.commit()


def remove_invite(conn: sqlite3.Connection, email: str) -> None:
    conn.execute("DELETE FROM invites WHERE email = lower(?)", (email.strip(),))
    conn.commit()


def list_invites(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM invites ORDER BY created_at")]


def list_users(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id")]


def set_disabled(conn: sqlite3.Connection, user_id: int, disabled: bool, now: datetime) -> None:
    if disabled:
        target = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        others = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND disabled_at IS NULL AND id != ?",
                              (user_id,)).fetchone()[0]
        if target and target["is_admin"] and others == 0:
            raise LastAdmin("There must be at least one admin")
        conn.execute("UPDATE users SET disabled_at = ? WHERE id = ?", (iso(now), user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    else:
        conn.execute("UPDATE users SET disabled_at = NULL WHERE id = ?", (user_id,))
    conn.commit()


def set_outreach(conn: sqlite3.Connection, user_id: int, enabled: bool) -> None:
    conn.execute("UPDATE users SET outreach_enabled = ? WHERE id = ?", (int(enabled), user_id))
    if not enabled:  # drafts and history stay (hidden by the gate); the Gmail grant goes
        conn.execute("DELETE FROM gmail_tokens WHERE user_id = ?", (user_id,))
    conn.commit()


def outreach_user_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE outreach_enabled = 1 AND disabled_at IS NULL").fetchone()[0]
