import io
import tarfile
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from jobseeker.backup.archive import write_archive
from jobseeker.backup.crypto import encrypt
from jobseeker.backup.restore import RestoreError, restore
from jobseeker.cli import app
from jobseeker.db.core import connect

NOW = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)
KEY = bytes(range(32))


def _archive(settings, tmp_path):
    settings = settings.model_copy(update={"backup_dir": tmp_path / "bk"})
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO runs (started_at) VALUES ('2026-10-08T00:00:00+00:00')")
    conn.commit()
    conn.close()
    (settings.data_dir / "users" / "1").mkdir(parents=True)
    (settings.data_dir / "users" / "1" / "resume.pdf").write_bytes(b"%PDF owner")
    return write_archive(settings, NOW)


def test_restore_plain_and_encrypted(settings, tmp_path):
    out = _archive(settings, tmp_path)
    report = restore(out, tmp_path / "r1", None)
    assert report["manifest_counts"] == report["restored_counts"]
    assert (tmp_path / "r1" / "data/users/1/resume.pdf").read_bytes() == b"%PDF owner"
    enc = tmp_path / (out.name + ".enc")
    enc.write_bytes(encrypt(out.read_bytes(), KEY))
    assert restore(enc, tmp_path / "r2", KEY)["restored_counts"]["runs"] == 1


def test_restore_refuses_non_empty_target(settings, tmp_path):
    out = _archive(settings, tmp_path)
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "x").write_text("x")
    with pytest.raises(RestoreError, match="not empty"):
        restore(out, tmp_path / "busy", None)


def test_restore_refuses_path_traversal(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        data = b"evil"
        info = tarfile.TarInfo("../evil.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(RestoreError, match="not allowed"):
        restore(bad, tmp_path / "r", None)
    assert not (tmp_path / "r").exists() and not (tmp_path / "evil.txt").exists()


def test_restore_detects_tampering(settings, tmp_path):
    out = _archive(settings, tmp_path)
    tampered = tmp_path / "t.tar.gz"
    with tarfile.open(out) as src, tarfile.open(tampered, "w:gz") as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read()
            if m.name == "data/users/1/resume.pdf":
                data = b"%PDF changed"
                m.size = len(data)
            dst.addfile(m, io.BytesIO(data))
    with pytest.raises(RestoreError, match="sha256 mismatch"):
        restore(tampered, tmp_path / "r", None)
    assert not (tmp_path / "r").exists()


def test_restore_wrong_key(settings, tmp_path):
    out = _archive(settings, tmp_path)
    enc = tmp_path / "x.tar.gz.enc"
    enc.write_bytes(encrypt(out.read_bytes(), KEY))
    with pytest.raises(RestoreError, match="wrong BACKUP_KEY"):
        restore(enc, tmp_path / "r", bytes(32))


def test_restore_cli(settings, tmp_path, monkeypatch):
    out = _archive(settings, tmp_path)
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    result = CliRunner().invoke(app, ["restore", str(out), "--to", str(tmp_path / "cli")])
    assert result.exit_code == 0, result.output
    assert "runs" in result.output and "integrity ok" in result.output


def _rewrite(out, dst, *, manifest=None, extra=None):
    """Copy archive `out` to `dst`, optionally editing MANIFEST.json (a function of its dict) or adding a member."""
    import json
    with tarfile.open(out) as src, tarfile.open(dst, "w:gz") as tar:
        for m in src.getmembers():
            data = src.extractfile(m).read()
            if m.name == "MANIFEST.json" and manifest:
                data = json.dumps(manifest(json.loads(data))).encode()
                m.size = len(data)
            tar.addfile(m, io.BytesIO(data))
        if extra:
            info = tarfile.TarInfo(extra)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    return dst


def test_restore_rejects_a_manifest_path_outside_the_allow_list(settings, tmp_path):
    def evil(m):
        m["files"].append({"path": "/etc/shadow", "sha256": "0" * 64})
        return m
    bad = _rewrite(_archive(settings, tmp_path), tmp_path / "m.tar.gz", manifest=evil)
    with pytest.raises(RestoreError, match="manifest path '/etc/shadow' is not allowed"):
        restore(bad, tmp_path / "r", None)
    assert not (tmp_path / "r").exists()


def test_restore_rejects_a_member_the_manifest_does_not_list(settings, tmp_path):
    bad = _rewrite(_archive(settings, tmp_path), tmp_path / "x.tar.gz", extra="data/users/1/unlisted.txt")
    with pytest.raises(RestoreError, match="manifest does not match"):
        restore(bad, tmp_path / "r", None)


def test_restore_rejects_a_manifest_entry_with_no_member(settings, tmp_path):
    def ghost(m):
        m["files"].append({"path": "data/users/1/ghost.pdf", "sha256": "0" * 64})
        return m
    bad = _rewrite(_archive(settings, tmp_path), tmp_path / "g.tar.gz", manifest=ghost)
    with pytest.raises(RestoreError, match="manifest does not match"):
        restore(bad, tmp_path / "r", None)
