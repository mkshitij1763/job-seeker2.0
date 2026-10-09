"""Once per IST day: local archive, then an encrypted copy in B2. A failed upload never raises (ok=False)."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import httpx

from jobseeker.backup.archive import apply_retention, write_archive
from jobseeker.backup.crypto import BackupKeyError, encrypt, load_key
from jobseeker.backup.s3 import OffsiteConfigError, S3Config, UploadError, put_object
from jobseeker.clock import app_day
from jobseeker.db.core import iso

NOT_CONFIGURED = "Off-site backup isn't configured"
NO_KEY = "BACKUP_KEY is not set, so nothing was uploaded"


class BackupFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupResult:
    path: Path | None
    ok: bool
    uploaded: bool
    error: str | None
    skipped: bool = False


def _row_ok(row) -> bool:
    return row["uploaded_at"] is not None or row["upload_error"] == NOT_CONFIGURED


def recent_backups(conn: sqlite3.Connection, n: int = 7) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM backups ORDER BY day DESC LIMIT ?", (n,))]


def _upload(settings, path: Path, day: str, now: datetime, client, sleep) -> tuple[bool, str | None]:
    try:
        cfg = S3Config.from_settings(settings)
    except OffsiteConfigError as e:
        return False, str(e)
    if cfg is None:
        return False, NOT_CONFIGURED
    if not settings.backup_key:
        return False, NO_KEY
    try:
        blob = encrypt(path.read_bytes(), load_key(settings.backup_key))
    except (BackupKeyError, ValueError) as e:
        return False, str(e)
    keys = [f"daily/{path.name}.enc"] + ([f"weekly/{path.name}.enc"] if date.fromisoformat(day).weekday() == 6 else [])
    own = client is None
    client = client or httpx.Client()
    try:
        for key in keys:
            put_object(client, cfg, key, blob, now, sleep=sleep)
    except UploadError as e:
        return False, str(e)
    finally:
        if own:
            client.close()
    return True, None


def nightly_backup(conn: sqlite3.Connection, settings, now: datetime, force: bool = False, client=None,
                   sleep=time.sleep) -> BackupResult:
    day = app_day(now)
    row = conn.execute("SELECT * FROM backups WHERE day = ?", (day,)).fetchone()
    if row is not None and not force and _row_ok(row):
        return BackupResult(Path(row["local_path"]), True, row["uploaded_at"] is not None, row["upload_error"],
                            skipped=True)
    try:
        path = write_archive(settings, now)
        apply_retention(path.parent)
    except Exception as e:
        raise BackupFailed(f"{type(e).__name__}: {e}") from e
    conn.execute("""INSERT INTO backups (day, local_path, size_bytes, uploaded_at, upload_error, created_at)
                    VALUES (?, ?, ?, NULL, NULL, ?)
                    ON CONFLICT (day) DO UPDATE SET local_path = excluded.local_path,
                      size_bytes = excluded.size_bytes, uploaded_at = NULL, upload_error = NULL,
                      created_at = excluded.created_at""", (day, str(path), path.stat().st_size, iso(now)))
    conn.commit()
    uploaded, error = _upload(settings, path, day, now, client, sleep)
    conn.execute("UPDATE backups SET uploaded_at = ?, upload_error = ? WHERE day = ?",
                 (iso(now) if uploaded else None, error, day))
    conn.commit()
    return BackupResult(path, uploaded or error == NOT_CONFIGURED, uploaded, error)
