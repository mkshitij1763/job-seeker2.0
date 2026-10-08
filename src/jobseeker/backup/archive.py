"""The nightly archive: DB snapshot, resumes and app config. Never .env or secrets/."""
from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import tarfile
import tempfile
from datetime import date, datetime
from pathlib import Path

from jobseeker.clock import app_day
from jobseeker.db.backup import snapshot
from jobseeker.db.core import iso

NAME = re.compile(r"^jobseeker-(\d{4}-\d{2}-\d{2})\.tar\.gz$")
_USER_FILE = re.compile(r"^data/users/\d+/[A-Za-z0-9._-]+$")


def member_allowed(name: str) -> bool:
    if name.startswith("/") or ".." in name.split("/"):
        return False
    return name in ("jobseeker.db", "MANIFEST.json", "config/app.yaml") or bool(_USER_FILE.match(name))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_archive(settings, now: datetime) -> Path:
    dest = settings.backup_path
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"jobseeker-{app_day(now)}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "jobseeker.db"
        snapshot(settings.db_path, db_copy)
        conn = sqlite3.connect(db_copy)
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        files: list[tuple[str, Path]] = [("jobseeker.db", db_copy)]
        app_yaml = settings.jobseeker_home / "config" / "app.yaml"
        if app_yaml.is_file():
            files.append(("config/app.yaml", app_yaml))
        users = settings.data_dir / "users"
        if users.is_dir():
            files += sorted((f"data/users/{p.relative_to(users).as_posix()}", p) for p in users.rglob("*") if p.is_file())
        files = [(name, path) for name, path in files if member_allowed(name)]
        manifest = {"created_at": iso(now), "user_version": version, "row_counts": counts,
                    "files": [{"path": name, "sha256": _sha(path)} for name, path in files]}
        partial = out.with_name(out.name + ".tmp")
        with tarfile.open(partial, "w:gz") as tar:
            for name, path in files:
                tar.add(path, arcname=name, recursive=False)
            data = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo("MANIFEST.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        partial.replace(out)
    return out


def apply_retention(dest: Path, keep_daily: int = 7, keep_sundays: int = 4) -> list[Path]:
    dated = sorted((date.fromisoformat(m.group(1)), p) for p in dest.glob("jobseeker-*.tar.gz")
                   if (m := NAME.match(p.name)))
    keep = {p for _, p in dated[-keep_daily:]} | {p for d, p in [x for x in dated if x[0].weekday() == 6][-keep_sundays:]}
    removed = [p for _, p in dated if p not in keep]
    for p in removed:
        p.unlink()
    return removed
