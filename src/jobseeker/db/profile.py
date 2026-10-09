from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from jobseeker.config import AppConfig, Preferences, UserPrefs, effective_prefs
from jobseeker.db.core import iso
from jobseeker.profile.facts import Facts

STALE_EXTRACT = timedelta(minutes=20)


def get_user_prefs(conn: sqlite3.Connection, user_id: int) -> UserPrefs:
    row = conn.execute("SELECT data FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return UserPrefs.model_validate_json(row["data"]) if row else UserPrefs()


def save_user_prefs(conn: sqlite3.Connection, user_id: int, up: UserPrefs, now: datetime) -> None:
    conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, updated_at) VALUES (?, ?, 1, 'roles', ?)
                    ON CONFLICT (user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at""",
                 (user_id, up.model_dump_json(), iso(now)))
    conn.commit()


def get_onboarding(conn, user_id: int) -> tuple[str | None, str | None]:
    row = conn.execute("SELECT onboarding_step, onboarded_at FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return (row["onboarding_step"], row["onboarded_at"]) if row else ("roles", None)


def set_onboarding(conn, user_id: int, step: str | None, onboarded_at: str | None, now: datetime) -> None:
    conn.execute("UPDATE user_prefs SET onboarding_step = ?, onboarded_at = ?, updated_at = ? WHERE user_id = ?",
                 (step, onboarded_at, iso(now), user_id))
    conn.commit()


def facts_row(conn, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM user_facts WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_facts(conn, user_id: int) -> Facts | None:
    row = facts_row(conn, user_id)
    return Facts.model_validate(json.loads(row["facts"])) if row and row["facts"] else None


def save_facts(conn, user_id: int, sha: str | None, facts: Facts, edited: bool, now: datetime) -> None:
    conn.execute("""INSERT INTO user_facts (user_id, resume_sha256, facts, edited, extract_status, updated_at)
                    VALUES (?, ?, ?, ?, 'done', ?)
                    ON CONFLICT (user_id) DO UPDATE SET resume_sha256 = excluded.resume_sha256, facts = excluded.facts,
                      edited = excluded.edited, extract_status = 'done', extract_error = '', updated_at = excluded.updated_at""",
                 (user_id, sha, facts.model_dump_json(), int(edited), iso(now)))
    conn.commit()


def claim_extract(conn, user_id: int, now: datetime) -> bool:
    conn.execute("INSERT OR IGNORE INTO user_facts (user_id, updated_at) VALUES (?, ?)", (user_id, iso(now)))
    cur = conn.execute("""UPDATE user_facts SET extract_status = 'running', extract_error = '', extract_started_at = ?
                          WHERE user_id = ? AND (extract_status != 'running' OR extract_started_at < ?)""",
                       (iso(now), user_id, iso(now - STALE_EXTRACT)))
    conn.commit()
    return cur.rowcount == 1


def extract_running(conn, user_id: int, now: datetime) -> bool:
    row = conn.execute("SELECT extract_status, extract_started_at FROM user_facts WHERE user_id = ?",
                       (user_id,)).fetchone()
    return bool(row) and row["extract_status"] == "running" and (row["extract_started_at"] or "") >= iso(now - STALE_EXTRACT)


def set_extract_status(conn, user_id: int, status: str, note: str = "") -> None:
    conn.execute("UPDATE user_facts SET extract_status = ?, extract_error = ? WHERE user_id = ?", (status, note, user_id))
    conn.commit()


def load_user_context(conn, user_id: int, cfg: AppConfig) -> tuple[Preferences, Facts | None]:
    user = conn.execute("SELECT name, email FROM users WHERE id = ?", (user_id,)).fetchone()
    return effective_prefs(get_user_prefs(conn, user_id), cfg, user["name"], user["email"]), get_facts(conn, user_id)
