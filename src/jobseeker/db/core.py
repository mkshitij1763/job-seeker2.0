from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jobseeker.db.migrations import SchemaOutOfDate, latest

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
SCHEMA_V0 = (Path(__file__).parent / "schema_v0.sql").read_text(encoding="utf-8")
# v0 only: tables/columns added after the MVP, so an old database reaches the exact shape migration 1 expects.
REQUIRED_TABLES = {"runs", "discovered_companies", "application_contacts", "contact_candidates",
                   "company_domains", "usage"}
NEW_COLUMNS = {
    "jobs": {"prescore": "INTEGER", "jd_attempts": "INTEGER NOT NULL DEFAULT 0"},
    "applications": {"find_status": "TEXT NOT NULL DEFAULT 'idle'", "find_error": "TEXT NOT NULL DEFAULT ''",
                     "find_started_at": "TEXT"},
    "company_domains": {"catch_all_at": "TEXT"},
    "application_contacts": {"nudged_at": "TEXT"},
}


def _catch_up_v0(conn: sqlite3.Connection, tables: set[str]) -> None:
    if not REQUIRED_TABLES <= tables:
        conn.executescript(SCHEMA_V0)  # every statement is IF NOT EXISTS
    changed = False
    for table, columns in NEW_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                changed = True
    if changed:
        conn.commit()


def connect(path: Path | str, *, check_version: bool = True) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    # Only touch the schema when something is missing, so a reader never needs a write lock while the daily run writes.
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not tables:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {latest()}")
        _seed_fresh(conn)
        conn.commit()
        return conn
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        _catch_up_v0(conn, tables)
    if check_version and version < latest():
        conn.close()
        raise SchemaOutOfDate(f"Database is at v{version}, the app needs v{latest()}. Run `jobseeker migrate`.")
    return conn


def _seed_fresh(conn: sqlite3.Connection) -> None:
    """A new database starts with its owner (user 1); ensure_owner() fills the email from OWNER_EMAIL."""
    conn.execute("INSERT INTO users (id, email, name, is_admin, created_at) VALUES (1, '', '', 1, ?)", (utcnow(),))
    conn.execute("INSERT INTO user_prefs (user_id, data, version, onboarding_step, updated_at) VALUES (1, '{}', 1, 'roles', ?)",
                 (utcnow(),))


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def utcnow() -> str:
    return iso(datetime.now(UTC))
