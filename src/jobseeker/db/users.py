from __future__ import annotations

import sqlite3

OWNER_ID = 1


def ensure_owner(conn: sqlite3.Connection, email: str) -> None:
    """Give user 1 the OWNER_EMAIL until they first sign in (after that, their Google identity is fixed)."""
    if email.strip():
        conn.execute("UPDATE users SET email = lower(?) WHERE id = ? AND google_sub IS NULL", (email.strip(), OWNER_ID))
        conn.commit()
