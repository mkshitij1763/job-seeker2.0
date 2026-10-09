import base64
from datetime import UTC, datetime

import httpx
import pytest
import respx

from jobseeker.backup.nightly import BackupFailed, nightly_backup, recent_backups
from jobseeker.db.core import connect

SUNDAY = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)   # Sunday in IST
MONDAY = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
ENDPOINT = "https://s3.us-west-004.backblazeb2.com"
OFFSITE = dict(backup_s3_endpoint=ENDPOINT, backup_s3_region="us-west-004", backup_s3_bucket="b",
               backup_s3_key_id="kid", backup_s3_secret="sec", backup_key=base64.b64encode(bytes(32)).decode())


def _setup(settings, tmp_path, **extra):
    s = settings.model_copy(update={"backup_dir": tmp_path / "bk", **extra})
    return s, connect(s.db_path)


def test_no_offsite_is_ok_with_notice(settings, tmp_path):
    s, conn = _setup(settings, tmp_path)
    r = nightly_backup(conn, s, MONDAY)
    assert r.ok and not r.uploaded and r.error == "Off-site backup isn't configured" and r.path.exists()
    assert recent_backups(conn)[0]["day"] == "2026-10-12"


@respx.mock
def test_uploads_daily_and_weekly_on_sunday(settings, tmp_path):
    s, conn = _setup(settings, tmp_path, **OFFSITE)
    daily = respx.put(f"{ENDPOINT}/b/daily/jobseeker-2026-10-11.tar.gz.enc").mock(return_value=httpx.Response(200))
    weekly = respx.put(f"{ENDPOINT}/b/weekly/jobseeker-2026-10-11.tar.gz.enc").mock(return_value=httpx.Response(200))
    r = nightly_backup(conn, s, SUNDAY)
    assert r.ok and r.uploaded and r.error is None and daily.called and weekly.called
    assert recent_backups(conn)[0]["uploaded_at"] is not None


@respx.mock
def test_monday_uploads_daily_only(settings, tmp_path):
    s, conn = _setup(settings, tmp_path, **OFFSITE)
    route = respx.put(url__regex=r".*/b/(daily|weekly)/.*").mock(return_value=httpx.Response(200))
    nightly_backup(conn, s, MONDAY)
    assert [c.request.url.path for c in route.calls] == ["/b/daily/jobseeker-2026-10-12.tar.gz.enc"]


@respx.mock
def test_failed_upload_is_not_ok_but_keeps_local_copy(settings, tmp_path):
    s, conn = _setup(settings, tmp_path, **OFFSITE)
    respx.put(url__regex=r".*").mock(return_value=httpx.Response(500))
    r = nightly_backup(conn, s, MONDAY, sleep=lambda x: None)
    assert not r.ok and not r.uploaded and "HTTP 500" in r.error and r.path.exists()
    assert recent_backups(conn)[0]["upload_error"].startswith("Upload of daily/")


def test_missing_backup_key_refuses_upload(settings, tmp_path):
    s, conn = _setup(settings, tmp_path, **{**OFFSITE, "backup_key": ""})
    r = nightly_backup(conn, s, MONDAY)
    assert not r.ok and r.error == "BACKUP_KEY is not set, so nothing was uploaded"


def test_partial_offsite_settings_is_an_error(settings, tmp_path):
    s, conn = _setup(settings, tmp_path, backup_s3_endpoint=ENDPOINT)
    r = nightly_backup(conn, s, MONDAY)
    assert not r.ok and "missing BACKUP_S3_REGION" in r.error and "BACKUP_S3_SECRET" in r.error


def test_idempotent_per_ist_day(settings, tmp_path, monkeypatch):
    s, conn = _setup(settings, tmp_path)
    first = nightly_backup(conn, s, MONDAY)
    calls = []
    monkeypatch.setattr("jobseeker.backup.nightly.write_archive", lambda *a: calls.append(a) or first.path)
    again = nightly_backup(conn, s, MONDAY)
    assert again.skipped and again.ok and calls == []
    forced = nightly_backup(conn, s, MONDAY, force=True)
    assert not forced.skipped and len(calls) == 1


@respx.mock
def test_failed_day_is_redone(settings, tmp_path):
    s, conn = _setup(settings, tmp_path, **OFFSITE)
    route = respx.put(url__regex=r".*").mock(side_effect=[httpx.Response(500)] * 3 + [httpx.Response(200)])
    assert not nightly_backup(conn, s, MONDAY, sleep=lambda x: None).ok
    second = nightly_backup(conn, s, MONDAY, sleep=lambda x: None)
    assert second.ok and not second.skipped and route.call_count == 4


def test_archive_failure_raises_and_records_nothing(settings, tmp_path, monkeypatch):
    s, conn = _setup(settings, tmp_path)
    monkeypatch.setattr("jobseeker.backup.nightly.write_archive", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(BackupFailed, match="disk full"):
        nightly_backup(conn, s, MONDAY)
    assert recent_backups(conn) == []
