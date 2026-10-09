import gzip
import sqlite3
from datetime import UTC, datetime, timedelta

from jobseeker.config import Settings
from jobseeker.db.backup import backup
from jobseeker.db.core import connect


def test_backup_writes_a_restorable_copy_and_keeps_the_last_seven(tmp_path):
    db = tmp_path / "jobseeker.db"
    conn = connect(db)
    conn.execute("INSERT INTO runs (started_at) VALUES ('2026-10-08T00:00:00+00:00')")
    conn.commit()
    dest = tmp_path / "backups"
    start = datetime(2026, 10, 1, tzinfo=UTC)
    for day in range(9):
        out = backup(db, dest, start + timedelta(days=day))
    assert out.name == "jobseeker-2026-10-09.db.gz"
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress(out.read_bytes()))
    assert sqlite3.connect(restored).execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert len(list(dest.glob("jobseeker-*.db.gz"))) == 7
    assert not (dest / "jobseeker-2026-10-02.db.gz").exists()


def test_backup_dir_prefers_explicit_setting(tmp_path):
    assert Settings(jobseeker_home=tmp_path, backup_dir=tmp_path / "b").backup_path == tmp_path / "b"
    assert Settings(jobseeker_home=tmp_path).backup_path.name in {"JobSeeker-backups"}


def test_backup_command(settings, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from jobseeker.cli import app

    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    connect(settings.db_path).close()
    out = CliRunner().invoke(app, ["backup"]).output
    assert "Backup written to" in out and "Off-site backup isn't configured" in out
    assert len(list((tmp_path / "bk").glob("jobseeker-*.tar.gz"))) == 1
