from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
# Columns added after the MVP; connect() adds them to older databases.
NEW_JOB_COLUMNS = {"prescore": "INTEGER", "jd_attempts": "INTEGER NOT NULL DEFAULT 0"}


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    # Only touch the schema when something is missing, so a reader never needs a write lock while the daily run writes.
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'discovered_companies'"
    ).fetchone() is None:
        conn.executescript(SCHEMA)  # every statement is IF NOT EXISTS: creates a fresh DB or adds new tables
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    missing = [(name, ddl) for name, ddl in NEW_JOB_COLUMNS.items() if name not in columns]
    for name, ddl in missing:
        conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
    if missing:
        conn.commit()
    return conn


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def utcnow() -> str:
    return iso(datetime.now(UTC))
