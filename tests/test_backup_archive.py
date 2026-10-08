import json
import tarfile
from datetime import UTC, date, datetime, timedelta

from jobseeker.backup.archive import apply_retention, member_allowed, write_archive
from jobseeker.db.core import connect

NOW = datetime(2026, 10, 11, 18, 40, tzinfo=UTC)  # 00:10 IST on 2026-10-12


def _home(settings):
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO runs (started_at) VALUES ('2026-10-08T00:00:00+00:00')")
    conn.commit()
    conn.close()
    (settings.data_dir / "users" / "2").mkdir(parents=True)
    (settings.data_dir / "users" / "2" / "resume.pdf").write_bytes(b"%PDF-1.7 roommate")
    (settings.jobseeker_home / "config").mkdir(exist_ok=True)
    (settings.jobseeker_home / "config" / "app.yaml").write_text("timezone: Asia/Kolkata\n")
    (settings.jobseeker_home / ".env").write_text("SECRET_KEY=never-in-backups\n")
    (settings.jobseeker_home / "secrets").mkdir(exist_ok=True)
    (settings.jobseeker_home / "secrets" / "token.json").write_text("{}")


def test_archive_members_are_exactly_the_allowed_set(settings, tmp_path):
    settings = settings.model_copy(update={"backup_dir": tmp_path / "bk"})
    _home(settings)
    out = write_archive(settings, NOW)
    assert out.name == "jobseeker-2026-10-12.tar.gz"  # IST date
    with tarfile.open(out) as tar:
        names = sorted(tar.getnames())
        assert names == ["MANIFEST.json", "config/app.yaml", "data/users/2/resume.pdf", "jobseeker.db"]
        manifest = json.loads(tar.extractfile("MANIFEST.json").read())
        assert b"never-in-backups" not in b"".join(tar.extractfile(m).read() for m in tar.getmembers() if m.isfile())
    assert manifest["row_counts"]["runs"] == 1
    assert {f["path"] for f in manifest["files"]} == {"jobseeker.db", "config/app.yaml", "data/users/2/resume.pdf"}
    assert all(len(f["sha256"]) == 64 for f in manifest["files"])
    assert not list((tmp_path / "bk").glob("*.tmp"))


def test_member_allowed():
    for ok in ("jobseeker.db", "MANIFEST.json", "config/app.yaml", "data/users/1/resume.pdf"):
        assert member_allowed(ok)
    for bad in ("../etc/passwd", "/abs", ".env", "data/users/../../x", "secrets/token.json", "data/other.db"):
        assert not member_allowed(bad)


def test_retention_keeps_7_daily_and_4_sundays(tmp_path):
    start = date(2026, 9, 1)
    for i in range(40):
        (tmp_path / f"jobseeker-{start + timedelta(days=i)}.tar.gz").write_bytes(b"x")
    (tmp_path / "jobseeker-2026-08-01.db.gz").write_bytes(b"old mac format")
    (tmp_path / "facts-2026-08-01.json").write_text("{}")
    apply_retention(tmp_path)
    kept = sorted(p.name for p in tmp_path.glob("jobseeker-*.tar.gz"))
    last7 = [f"jobseeker-{start + timedelta(days=i)}.tar.gz" for i in range(33, 40)]
    sundays = sorted(f"jobseeker-{d}.tar.gz" for d in (start + timedelta(days=i) for i in range(40))
                     if d.weekday() == 6)[-4:]
    assert kept == sorted(set(last7) | set(sundays))
    assert (tmp_path / "jobseeker-2026-08-01.db.gz").exists() and (tmp_path / "facts-2026-08-01.json").exists()
