from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from jobseeker.config import Company
from jobseeker.db.core import iso, utcnow

RECHECK_DAYS = 30


def get_company(conn: sqlite3.Connection, name_norm: str) -> dict | None:
    row = conn.execute("SELECT * FROM discovered_companies WHERE name_norm = ?", (name_norm,)).fetchone()
    return dict(row) if row else None


def record_company(conn: sqlite3.Connection, name_norm: str, display_name: str, status: str,
                   ats: str | None = None, slug: str | None = None, now: datetime | None = None) -> None:
    conn.execute(
        """INSERT INTO discovered_companies (name_norm, display_name, ats, slug, status, checked_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT (name_norm) DO UPDATE SET display_name = excluded.display_name, ats = excluded.ats,
             slug = excluded.slug, status = excluded.status, checked_at = excluded.checked_at""",
        (name_norm, display_name, ats, slug, status, iso(now) if now else utcnow()),
    )
    conn.commit()


def needs_check(conn: sqlite3.Connection, name_norm: str, now: datetime) -> bool:
    row = get_company(conn, name_norm)
    if row is None:
        return True
    if row["status"] == "active":
        return False
    return row["checked_at"] <= iso(now - timedelta(days=RECHECK_DAYS))


def active_companies(conn: sqlite3.Connection) -> list[tuple[str, Company]]:
    rows = conn.execute(
        "SELECT name_norm, display_name, ats, slug FROM discovered_companies WHERE status = 'active' ORDER BY id"
    ).fetchall()
    return [(r["name_norm"], Company(name=r["display_name"], ats=r["ats"], slug=r["slug"])) for r in rows]


def mark_inactive(conn: sqlite3.Connection, name_norm: str, now: datetime) -> None:
    conn.execute("UPDATE discovered_companies SET status = 'inactive', checked_at = ? WHERE name_norm = ?",
                 (iso(now), name_norm))
    conn.commit()


def bump_jobs_seen(conn: sqlite3.Connection, name_norm: str, n: int = 1) -> bool:
    """False when the company isn't recorded (yet), so the caller can count it after discovery."""
    cur = conn.execute("UPDATE discovered_companies SET jobs_seen = jobs_seen + ? WHERE name_norm = ?",
                       (n, name_norm))
    conn.commit()
    return cur.rowcount == 1


def list_companies(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM discovered_companies
           ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'none' THEN 1 ELSE 2 END, jobs_seen DESC, id"""
    ).fetchall()
    return [dict(r) for r in rows]
