from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

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
        # Job sites list without descriptions; never wipe one fetched separately.
        if not jd_text.strip() and row["jd_text"].strip():
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


def _upsert_verdict(conn: sqlite3.Connection, user_id: int, job_id: int, column: str, value) -> None:
    conn.execute(
        f"""INSERT INTO user_jobs (user_id, job_id, {column}, jd_hash, evaluated_at)
            SELECT ?, id, ?, jd_hash, ? FROM jobs WHERE id = ?
            ON CONFLICT (user_id, job_id) DO UPDATE SET {column} = excluded.{column},
              jd_hash = excluded.jd_hash, evaluated_at = excluded.evaluated_at""",
        (user_id, value, utcnow(), job_id))
    conn.commit()


def set_filter_reason(conn: sqlite3.Connection, user_id: int, job_id: int, reason: str) -> None:
    _upsert_verdict(conn, user_id, job_id, "filter_reason", reason)


def get_user_job(conn: sqlite3.Connection, user_id: int, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM user_jobs WHERE user_id = ? AND job_id = ?", (user_id, job_id)).fetchone()
    return dict(row) if row else None


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def set_prescore(conn: sqlite3.Connection, user_id: int, job_id: int, score: int) -> None:
    _upsert_verdict(conn, user_id, job_id, "prescore", score)


def set_jd_text(conn: sqlite3.Connection, job_id: int, text: str) -> None:
    """Store a fetched description, keeping whichever text is longer."""
    row = conn.execute("SELECT jd_text FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row and len(text) > len(row["jd_text"]):
        conn.execute("UPDATE jobs SET jd_text = ?, jd_hash = ? WHERE id = ?", (text, jd_hash(text), job_id))
        conn.commit()


def record_jd_attempt(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("UPDATE jobs SET jd_attempts = jd_attempts + 1 WHERE id = ?", (job_id,))
    conn.commit()


def expire_unscored(conn: sqlite3.Connection, user_id: int, now: datetime, max_age_days: int) -> int:
    cutoff = iso(now - timedelta(days=max_age_days))
    cur = conn.execute(
        """UPDATE user_jobs SET filter_reason = 'stale: never scored'
           WHERE user_id = ? AND filter_reason IS NULL
           AND job_id IN (SELECT id FROM jobs WHERE COALESCE(posted_at, first_seen_at) < ?)
           AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.user_id = user_jobs.user_id AND s.job_id = user_jobs.job_id)""",
        (user_id, cutoff))
    expired = cur.rowcount
    cur = conn.execute(  # old jobs this user has no verdict for yet (never evaluated): expire those too
        """INSERT INTO user_jobs (user_id, job_id, filter_reason, jd_hash, evaluated_at)
           SELECT ?, j.id, 'stale: never scored', j.jd_hash, ? FROM jobs j
           WHERE COALESCE(j.posted_at, j.first_seen_at) < ?
           AND NOT EXISTS (SELECT 1 FROM user_jobs uj WHERE uj.user_id = ? AND uj.job_id = j.id)
           AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.user_id = ? AND s.job_id = j.id)""",
        (user_id, iso(now), cutoff, user_id, user_id))
    conn.commit()
    return expired + cur.rowcount


_UJ = "LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = :u"


def jobs_missing_prescore(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        f"""SELECT j.* FROM jobs j {_UJ} WHERE uj.filter_reason IS NULL AND uj.prescore IS NULL
            AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.user_id = :u AND s.job_id = j.id) ORDER BY j.id""",
        {"u": user_id}).fetchall()
    return [dict(r) for r in rows]


def job_from_row(row: dict) -> Job:
    return Job(
        source=row["source"], source_job_id=row["source_job_id"], company=row["company"],
        title=row["title"], location=row["location"], remote=bool(row["remote"]),
        posted_at=datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None,
        salary_text=row["salary_text"], jd_text=row["jd_text"], apply_url=row["apply_url"],
        location_city=row["location_city"], is_remote=bool(row["remote"]),
        fingerprint=row["fingerprint"],
    )


def jobs_needing_score(conn: sqlite3.Connection, user_id: int, rubric_version: str, limit: int,
                       force: bool = False, with_jd: bool = False, profile_hash: str | None = None,
                       exclude: set[int] = frozenset()) -> list[dict]:
    """With profile_hash (the pipeline's call), a score is fresh only if its profile_hash matches too, and only
    jobs this user has evaluated (a user_jobs row) come back. exclude drops ids already handled this run."""
    tail = ("AND TRIM(j.jd_text) != '' " if with_jd else "") + \
        "ORDER BY COALESCE(uj.prescore, -1) DESC, j.first_seen_at DESC, j.id DESC LIMIT :limit"
    fresh = "" if force else """AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.user_id = :u AND s.job_id = j.id
                                    AND s.rubric_version = :rv AND s.jd_hash = j.jd_hash
                                    AND (:ph IS NULL OR s.profile_hash = :ph))"""
    skip = f"AND j.id NOT IN ({','.join(str(int(i)) for i in exclude)})" if exclude else ""
    evaluated = "AND uj.job_id IS NOT NULL" if profile_hash is not None else ""
    sql = (f"SELECT j.*, uj.prescore AS uj_prescore FROM jobs j {_UJ} WHERE uj.filter_reason IS NULL "
           f"{evaluated} {fresh} {skip} {tail}")
    params = {"u": user_id, "rv": rubric_version, "limit": limit, "ph": profile_hash}
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def save_score(conn: sqlite3.Connection, user_id: int, job_id: int, result: ScoreResult, model: str,
               rubric_version: str, jd_hash_value: str, *, profile_hash: str | None = None) -> None:
    conn.execute(
        """INSERT INTO scores (user_id, job_id, score, breakdown, matches, gaps, recommendation, role_family,
           model, rubric_version, jd_hash, created_at, profile_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, job_id, result.score, json.dumps(result.breakdown), json.dumps(result.matches),
         json.dumps(result.gaps), result.recommendation, result.role_family, model,
         rubric_version, jd_hash_value, utcnow(), profile_hash),
    )
    conn.commit()


def latest_score(conn: sqlite3.Connection, user_id: int, job_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM scores WHERE user_id = ? AND job_id = ? ORDER BY id DESC LIMIT 1", (user_id, job_id)
    ).fetchone()
    return dict(row) if row else None
