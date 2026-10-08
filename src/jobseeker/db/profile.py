from __future__ import annotations

import sqlite3

from jobseeker.config import UserPrefs


def get_user_prefs(conn: sqlite3.Connection, user_id: int) -> UserPrefs:
    row = conn.execute("SELECT data FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return UserPrefs.model_validate_json(row["data"]) if row else UserPrefs()
