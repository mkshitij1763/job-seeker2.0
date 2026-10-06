from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from jobseeker.config import Preferences, Rubric
from jobseeker.db.applications import (
    blocked_companies, ensure_application, get_application, get_status, save_draft, set_suggestion,
    transition, wake_snoozed,
)
from jobseeker.db.jobs import get_job, job_from_row, jobs_needing_score, save_score, set_filter_reason, upsert_job
from jobseeker.db.runs import finish_run, start_run
from jobseeker.llm import LLM, LLMError, LLMQuotaExceeded
from jobseeker.outreach.drafter import draft_outreach
from jobseeker.pipeline.normalize import normalize
from jobseeker.pipeline.prefilter import prefilter
from jobseeker.profile.facts import Facts
from jobseeker.scoring.scorer import score_job


@dataclass
class RunStats:
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    filtered: int = 0
    scored: int = 0
    shortlisted: int = 0
    drafted: int = 0
    errors: list[str] = field(default_factory=list)


def draft_application(conn: sqlite3.Connection, app_id: int, llm: LLM, facts: Facts, prefs: Preferences,
                      now: datetime | None = None) -> None:
    app = get_application(conn, app_id)
    job = job_from_row(get_job(conn, app["job_id"]))
    result = draft_outreach(llm, job, facts, prefs, prefs.models.drafting)
    b = result.bundle
    save_draft(conn, app_id, "email", b.email_subject, b.email_body)
    save_draft(conn, app_id, "li_note", "", b.li_note)
    save_draft(conn, app_id, "li_dm", "", b.li_dm)
    set_suggestion(conn, app_id, b.contact_role, b.contact_reason, result.linkedin_search_url, result.warnings)
    if get_status(conn, app_id) in ("new", "shortlisted"):
        transition(conn, app_id, "drafted", {"warnings": len(result.warnings)}, now)


def _apps_needing_drafts(conn: sqlite3.Connection, limit: int) -> list[int]:
    rows = conn.execute(
        """SELECT a.id FROM applications a
           JOIN scores s ON s.id = (SELECT id FROM scores WHERE job_id = a.job_id ORDER BY id DESC LIMIT 1)
           WHERE a.status = 'shortlisted' ORDER BY s.score DESC LIMIT ?""", (limit,)).fetchall()
    return [r["id"] for r in rows]


def run_daily(conn: sqlite3.Connection, *, sources, client, llm: LLM, facts: Facts, prefs: Preferences,
              rubric: Rubric, now: datetime | None = None, fetch: bool = True,
              force_rescore: bool = False) -> RunStats:
    now = now or datetime.now(UTC)
    stats = RunStats()
    run_id = start_run(conn, now)
    wake_snoozed(conn, now)

    if fetch:
        blocked = blocked_companies(conn)
        for src in sources:
            try:
                raws = src.fetch(client)
            except Exception as e:  # one broken source must never kill the run
                stats.errors.append(f"{src.name}: {type(e).__name__}: {e}")
                continue
            stats.fetched += len(raws)
            for raw in raws:
                job = normalize(raw)
                job_id, is_new = upsert_job(conn, job, now)
                if not is_new:
                    stats.duplicates += 1
                    continue
                stats.new += 1
                reason = prefilter(job, prefs, now, blocked)
                if reason:
                    set_filter_reason(conn, job_id, reason)
                    stats.filtered += 1

    quota_hit = False
    for row in jobs_needing_score(conn, rubric.version, prefs.budgets.score_per_run, force=force_rescore):
        try:
            result = score_job(llm, job_from_row(row), facts, prefs, rubric, prefs.models.scoring)
        except LLMQuotaExceeded as e:
            stats.errors.append(f"scoring stopped: {e}")
            quota_hit = True
            break
        except LLMError as e:
            stats.errors.append(f"score job {row['id']}: {e}")
            continue
        save_score(conn, row["id"], result, prefs.models.scoring, rubric.version, row["jd_hash"])
        stats.scored += 1
        app_id = ensure_application(conn, row["id"], now)
        if result.recommendation == "apply" and get_status(conn, app_id) == "new":
            transition(conn, app_id, "shortlisted", {"score": result.score}, now)
            stats.shortlisted += 1

    # Scoring and drafting use different models (separate daily quotas); skip drafting only if they share one.
    same_model = prefs.models.drafting == prefs.models.scoring
    drafting_apps = [] if (quota_hit and same_model) else _apps_needing_drafts(conn, prefs.budgets.draft_per_run)
    for app_id in drafting_apps:
        try:
            draft_application(conn, app_id, llm, facts, prefs, now)
            stats.drafted += 1
        except LLMQuotaExceeded as e:
            stats.errors.append(f"drafting stopped: {e}")
            break
        except LLMError as e:
            stats.errors.append(f"draft application {app_id}: {e}")

    data = asdict(stats)
    errors = data.pop("errors")
    finish_run(conn, run_id, data, errors, now)
    return stats
