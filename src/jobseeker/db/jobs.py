from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from jobseeker.db.core import iso, utcnow
from jobseeker.models import Job, ScoreResult, jd_hash


def _dt(value: datetime | None) -> str | None:
    return iso(value) if value else None


def upsert_job(conn: sqlite3.Connection, job: Job, now: datetime | None = None) -> tuple[int, bool]:
    seen_at = iso(now) if now else utcnow()
    h = jd_hash(job.jd_text)
    row = conn.execute(
        "SELECT id, jd_text, alt_urls FROM jobs WHERE source = ? AND source_job_id = ?",
        (job.source, job.source_job_id),
    ).fetchone()
    if row:
        jd_text = job.jd_text
        # A merged cross-source duplicate keeps the longest JD seen, whichever source refreshes it.
        if json.loads(row["alt_urls"]) and len(row["jd_text"]) > len(jd_text):
            jd_text = row["jd_text"]
        h = jd_hash(jd_text)
        conn.execute(
            """UPDATE jobs SET title=?, location=?, location_city=?, remote=?, posted_at=?,
               salary_text=?, jd_text=?, jd_hash=?, apply_url=? WHERE id=?""",
            (job.title, job.location, job.location_city, int(job.is_remote), _dt(job.posted_at),
             job.salary_text, jd_text, h, job.apply_url, row["id"]),
        )
        conn.commit()
        return row["id"], False

    dup = conn.execute(
        "SELECT id, jd_text, salary_text, alt_urls FROM jobs WHERE fingerprint = ? ORDER BY id LIMIT 1",
        (job.fingerprint,),
    ).fetchone()
    if dup:
        alts = json.loads(dup["alt_urls"])
        if job.apply_url not in alts:
            alts.append(job.apply_url)
        jd_text, salary = dup["jd_text"], dup["salary_text"] or job.salary_text
        if len(job.jd_text) > len(jd_text):
            jd_text = job.jd_text
        conn.execute(
            "UPDATE jobs SET alt_urls=?, jd_text=?, jd_hash=?, salary_text=? WHERE id=?",
            (json.dumps(alts), jd_text, jd_hash(jd_text), salary, dup["id"]),
        )
        conn.commit()
        return dup["id"], False

    cur = conn.execute(
        """INSERT INTO jobs (source, source_job_id, company, title, location, location_city, remote,
           posted_at, salary_text, jd_text, jd_hash, apply_url, fingerprint, first_seen_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job.source, job.source_job_id, job.company, job.title, job.location, job.location_city,
         int(job.is_remote), _dt(job.posted_at), job.salary_text, job.jd_text, h, job.apply_url,
         job.fingerprint, seen_at),
    )
    conn.commit()
    return cur.lastrowid, True


def set_filter_reason(conn: sqlite3.Connection, job_id: int, reason: str) -> None:
    conn.execute("UPDATE jobs SET filter_reason = ? WHERE id = ?", (reason, job_id))
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def job_from_row(row: dict) -> Job:
    return Job(
        source=row["source"], source_job_id=row["source_job_id"], company=row["company"],
        title=row["title"], location=row["location"], remote=bool(row["remote"]),
        posted_at=datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None,
        salary_text=row["salary_text"], jd_text=row["jd_text"], apply_url=row["apply_url"],
        location_city=row["location_city"], is_remote=bool(row["remote"]),
        fingerprint=row["fingerprint"],
    )


def jobs_needing_score(conn: sqlite3.Connection, rubric_version: str, limit: int,
                       force: bool = False) -> list[dict]:
    if force:
        sql = "SELECT * FROM jobs WHERE filter_reason IS NULL ORDER BY first_seen_at DESC, id DESC LIMIT ?"
        params: tuple = (limit,)
    else:
        sql = """SELECT j.* FROM jobs j WHERE j.filter_reason IS NULL AND NOT EXISTS (
                   SELECT 1 FROM scores s WHERE s.job_id = j.id
                   AND s.rubric_version = ? AND s.jd_hash = j.jd_hash)
                 ORDER BY j.first_seen_at DESC, j.id DESC LIMIT ?"""
        params = (rubric_version, limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def save_score(conn: sqlite3.Connection, job_id: int, result: ScoreResult, model: str,
               rubric_version: str, jd_hash_value: str) -> None:
    conn.execute(
        """INSERT INTO scores (job_id, score, breakdown, matches, gaps, recommendation, role_family,
           model, rubric_version, jd_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, result.score, json.dumps(result.breakdown), json.dumps(result.matches),
         json.dumps(result.gaps), result.recommendation, result.role_family, model,
         rubric_version, jd_hash_value, utcnow()),
    )
    conn.commit()


def latest_score(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM scores WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)
    ).fetchone()
    return dict(row) if row else None
