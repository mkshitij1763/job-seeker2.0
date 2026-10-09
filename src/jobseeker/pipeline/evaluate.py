"""Per-user job verdicts (filter reason + pre-score), re-applied after a preference change in both directions."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from jobseeker.config import Preferences
from jobseeker.db.applications import blocked_companies, get_status, transition
from jobseeker.db.core import iso
from jobseeker.db.jobs import expire_unscored, job_from_row, set_verdict
from jobseeker.pipeline.prefilter import prefilter
from jobseeker.pipeline.prescore import prescore
from jobseeker.profile.facts import Facts

BEFORE_OUTREACH = {"new", "shortlisted", "drafted"}  # from "approved" on, a Gmail draft exists


@dataclass
class Report:
    hidden: list[dict] = field(default_factory=list)
    restored: list[dict] = field(default_factory=list)
    new: list[dict] = field(default_factory=list)
    skipped_apps: list[int] = field(default_factory=list)
    kept_apps: list[int] = field(default_factory=list)


def skip_hidden_apps(conn: sqlite3.Connection, app_ids: list[int], reason: str, now: datetime) -> None:
    """Skip (undoably) the apps of jobs that just became hidden, if they haven't reached outreach yet."""
    for app_id in app_ids:
        if get_status(conn, app_id) in BEFORE_OUTREACH:
            transition(conn, app_id, "skipped", {"reason": reason}, now)


def verdict(job, prefs: Preferences, facts: Facts | None, now: datetime, blocked: set[str],
            scored: bool) -> tuple[str | None, int]:
    points = prescore(job, facts, prefs) if facts is not None else 0
    reason = prefilter(job, prefs, now, blocked)
    if reason and reason.startswith("stale:"):
        reason = None  # age isn't re-judged here; old jobs expire on their own
    if reason is None and not scored and points < prefs.min_prescore:
        reason = f"low pre-score: {points}"
    return reason, points


def reevaluate(conn: sqlite3.Connection, user_id: int, prefs: Preferences, facts: Facts | None, now: datetime,
               apply: bool) -> Report:
    blocked = blocked_companies(conn, user_id)
    cutoff = iso(now - timedelta(days=prefs.max_age_days))
    rows = conn.execute(
        """SELECT j.*, uj.filter_reason AS old_reason, uj.job_id AS has_row, a.id AS app_id, a.status AS app_status,
                  EXISTS (SELECT 1 FROM scores s WHERE s.user_id = :u AND s.job_id = j.id) AS scored
           FROM jobs j LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = :u
           LEFT JOIN applications a ON a.job_id = j.id AND a.user_id = :u
           WHERE COALESCE(j.posted_at, j.first_seen_at) >= :cutoff
           AND (uj.filter_reason IS NULL OR uj.filter_reason NOT LIKE 'stale:%')""",
        {"u": user_id, "cutoff": cutoff}).fetchall()
    report, writes = Report(), []
    for r in rows:
        r = dict(r)
        reason, points = verdict(job_from_row(r), prefs, facts, now, blocked, bool(r["scored"]))
        info = {"job_id": r["id"], "title": r["title"], "company": r["company"], "reason": reason}
        if r["has_row"] is None:
            report.new.append(info)
        elif r["old_reason"] is None and reason is not None:
            report.hidden.append(info)
        elif r["old_reason"] is not None and reason is None:
            report.restored.append(info)
        if r["app_id"] and reason is not None and r["old_reason"] is None:  # visible before (or never judged), hidden now
            (report.skipped_apps if r["app_status"] in BEFORE_OUTREACH else report.kept_apps).append(r["app_id"])
        writes.append((user_id, r["id"], reason, points, r["jd_hash"], iso(now)))
    if apply:
        conn.executemany(
            """INSERT INTO user_jobs (user_id, job_id, filter_reason, prescore, jd_hash, evaluated_at) VALUES (?,?,?,?,?,?)
               ON CONFLICT (user_id, job_id) DO UPDATE SET filter_reason = excluded.filter_reason,
                 prescore = excluded.prescore, jd_hash = excluded.jd_hash, evaluated_at = excluded.evaluated_at""", writes)
        conn.commit()
        skip_hidden_apps(conn, report.skipped_apps, "settings: preferences changed", now)
    return report


@dataclass
class EvalStats:
    evaluated: int = 0
    filtered: int = 0
    below_cutoff: int = 0


def evaluate(conn, user_id: int, prefs, facts, now, heartbeat: Callable[[], None] = lambda: None) -> EvalStats:
    """Verdicts for live jobs this user has never judged, or whose description changed. Like reevaluate, a job
    that goes from visible (or never judged) to hidden skips its app if outreach hasn't started."""
    expire_unscored(conn, user_id, now, prefs.max_age_days)
    blocked = blocked_companies(conn, user_id)
    rows = conn.execute(
        """SELECT j.*, uj.job_id AS uj_job, uj.filter_reason AS old_reason, a.id AS app_id, a.status AS app_status
           FROM jobs j
           LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = ?
           LEFT JOIN applications a ON a.job_id = j.id AND a.user_id = ?
           WHERE COALESCE(j.posted_at, j.first_seen_at) >= ? AND (uj.job_id IS NULL OR uj.jd_hash != j.jd_hash)
           ORDER BY j.id""", (user_id, user_id, iso(now - timedelta(days=prefs.max_age_days)))).fetchall()
    stats, newly_hidden = EvalStats(), []
    for i, row in enumerate(rows, 1):
        new = row["uj_job"] is None
        # verdict's `scored` flag means "skip the pre-score cutoff": True for a changed description (spec §4.4)
        reason, points = verdict(job_from_row(dict(row)), prefs, facts, now, blocked, not new)
        set_verdict(conn, user_id, row["id"], reason, points, row["jd_hash"], now)
        if row["app_id"] and reason is not None and row["old_reason"] is None and row["app_status"] in BEFORE_OUTREACH:
            newly_hidden.append(row["app_id"])
        stats.evaluated += 1
        if reason and reason.startswith("low pre-score"):
            stats.below_cutoff += 1
        elif reason:
            stats.filtered += 1
        if i % 500 == 0:
            conn.commit()
            heartbeat()
    conn.commit()
    skip_hidden_apps(conn, newly_hidden, "pipeline: the job description changed", now)
    return stats
