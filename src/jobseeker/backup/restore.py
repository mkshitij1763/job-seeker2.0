"""Unpack a backup into an empty directory and check it. Never touches the live JOBSEEKER_HOME."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import tarfile
from pathlib import Path

from jobseeker.backup.archive import member_allowed
from jobseeker.backup.crypto import BackupDecryptError, decrypt


class RestoreError(RuntimeError):
    pass


def _open(path: Path, key: bytes | None) -> tarfile.TarFile:
    data = path.read_bytes()
    if path.name.endswith(".enc"):
        if key is None:
            raise RestoreError("This file is encrypted: set BACKUP_KEY")
        try:
            data = decrypt(data, key)
        except BackupDecryptError as e:
            raise RestoreError(str(e)) from e
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")


def restore(path: Path, to: Path, key: bytes | None) -> dict:
    if to.exists() and any(to.iterdir()):
        raise RestoreError(f"{to} is not empty")
    created = not to.exists()
    to.mkdir(parents=True, exist_ok=True)
    try:
        with _open(path, key) as tar:
            members = tar.getmembers()
            for m in members:
                if not member_allowed(m.name) or not m.isfile():
                    raise RestoreError(f"archive member {m.name!r} is not allowed")
            names = {m.name for m in members}
            if "MANIFEST.json" not in names:
                raise RestoreError("archive has no MANIFEST.json")
            manifest = json.loads(tar.extractfile("MANIFEST.json").read())
            listed = [f["path"] for f in manifest["files"]]
            for name in listed:
                if not isinstance(name, str) or name == "MANIFEST.json" or not member_allowed(name):
                    raise RestoreError(f"manifest path {name!r} is not allowed")
            if sorted(listed) != sorted(names - {"MANIFEST.json"}):  # every file is listed once, and nothing more
                raise RestoreError("manifest does not match the archive's files")
            for m in members:
                dest = to / m.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(tar.extractfile(m).read())
        for f in manifest["files"]:
            if hashlib.sha256((to / f["path"]).read_bytes()).hexdigest() != f["sha256"]:
                raise RestoreError(f"sha256 mismatch for {f['path']}")
        conn = sqlite3.connect(to / "jobseeker.db")
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RestoreError("PRAGMA integrity_check failed")
            counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                      for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        return {"manifest_counts": manifest["row_counts"], "restored_counts": counts}
    except (RestoreError, OSError, tarfile.TarError, KeyError, TypeError, json.JSONDecodeError) as e:
        if created:
            shutil.rmtree(to, ignore_errors=True)
        else:
            for child in to.iterdir():
                shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
        raise e if isinstance(e, RestoreError) else RestoreError(f"{type(e).__name__}: {e}") from e
