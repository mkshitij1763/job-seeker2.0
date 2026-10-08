"""Versioned schema migrations (PRAGMA user_version), run only by `jobseeker migrate`."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class SchemaOutOfDate(RuntimeError):
    pass


class DatabaseBusy(RuntimeError):
    pass


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrationContext:
    owner_email: str
    now: datetime
    home: Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection, MigrationContext], None]


MIGRATIONS: list[Migration] = []


def latest(migrations: list[Migration] | None = None) -> int:
    ms = MIGRATIONS if migrations is None else migrations
    return ms[-1].version if ms else 0


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def _version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _check_not_busy(db_path: Path, busy_timeout: float) -> None:
    probe = sqlite3.connect(db_path, timeout=busy_timeout)
    try:
        probe.execute("BEGIN IMMEDIATE")
        probe.rollback()
    except sqlite3.OperationalError as e:
        raise DatabaseBusy("Database is busy: stop jobseeker-web and the tick timer first") from e
    finally:
        probe.close()


def migrate(db_path: Path, ctx: MigrationContext, backup_dir: Path, *, migrations: list[Migration] | None = None,
            dry_run: bool = False, busy_timeout: float = 5.0) -> list[str]:
    """Back up, then apply every pending migration in its own transaction with foreign keys off; a failed
    foreign_key_check rolls that migration back. dry_run migrates a temporary copy and leaves the file untouched."""
    from jobseeker.db.backup import snapshot
    from jobseeker.db.core import connect

    ms = MIGRATIONS if migrations is None else migrations
    db_path = Path(db_path)
    _check_not_busy(db_path, busy_timeout)
    if dry_run:
        tmp = Path(tempfile.mkdtemp())
        try:
            work = snapshot(db_path, tmp / db_path.name)
            return ["(dry run)"] + migrate(work, ctx, tmp / "bk", migrations=ms)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    conn = connect(db_path, check_version=False)
    try:
        start = _version(conn)
        pending = [x for x in ms if x.version > start]
        if not pending:
            return [f"Already at v{start}"]
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot(db_path, backup_dir / f"pre-migrate-v{start}-{ctx.now:%Y%m%d-%H%M%S}.db")
        before = table_counts(conn)
        report = []
        for mig in pending:
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")  # only takes effect outside a transaction
            conn.execute("BEGIN IMMEDIATE")
            try:
                mig.apply(conn, ctx)
                bad = conn.execute("PRAGMA foreign_key_check").fetchall()
                if bad:
                    raise MigrationError(f"v{mig.version}: foreign key check failed: {[tuple(r) for r in bad][:10]}")
                conn.execute(f"PRAGMA user_version = {mig.version}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")
            report.append(f"Applied v{mig.version}: {mig.name}")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("integrity_check failed after migrating")
        after = table_counts(conn)
        report += [f"  {t}: {before.get(t, '-')} -> {after.get(t, '-')}" for t in sorted(set(before) | set(after))]
        return report
    finally:
        conn.close()
