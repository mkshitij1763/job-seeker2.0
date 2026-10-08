from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

KEEP = 7


def snapshot(db_path: Path, out: Path) -> Path:
    """A consistent copy of a live (WAL) database through SQLite's backup API."""
    out.parent.mkdir(parents=True, exist_ok=True)
    src, dst = sqlite3.connect(db_path), sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return out


def backup(db_path: Path, dest: Path, now: datetime, keep: int = KEEP) -> Path:
    """Write a consistent, gzipped copy of the database for today; keep the newest `keep`."""
    dest.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y-%m-%d")
    out = dest / f"jobseeker-{day}.db.gz"
    with tempfile.TemporaryDirectory() as tmp:
        copy = snapshot(db_path, Path(tmp) / "snapshot.db")  # safe while the dashboard is writing (WAL)
        with copy.open("rb") as f, gzip.open(out.with_suffix(".tmp"), "wb") as g:
            shutil.copyfileobj(f, g)
    out.with_suffix(".tmp").replace(out)  # never leave a half-written backup under the real name
    for old in sorted(dest.glob("jobseeker-*.db.gz"))[:-keep]:
        old.unlink()
    return out
