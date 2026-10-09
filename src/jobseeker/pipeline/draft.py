"""Stage 7: AI drafts for eligible users, best score first, round-robin, inside each user's daily share."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from jobseeker.clock import app_now
from jobseeker.db.applications import get_application, get_status, save_draft, set_suggestion, transition
from jobseeker.db.jobs import get_job, job_from_row
from jobseeker.db.usage import Budget, Limit
from jobseeker.llm import LLMError, LLMQuotaExceeded, LLMUnavailable
from jobseeker.outreach.drafter import draft_outreach
from jobseeker.pipeline.eligible import share_divisor


def draft_application(conn, app_id: int, llm, facts, prefs, now: datetime | None = None) -> None:
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


def apps_needing_drafts(conn, user_id: int, limit: int, exclude: set[int]) -> list[int]:
    skip = f"AND a.id NOT IN ({','.join(str(int(i)) for i in exclude)})" if exclude else ""
    rows = conn.execute(
        f"""SELECT a.id FROM applications a
            JOIN scores s ON s.id = (SELECT id FROM scores WHERE job_id = a.job_id AND user_id = a.user_id
                                     ORDER BY id DESC LIMIT 1)
            LEFT JOIN user_jobs uj ON uj.user_id = a.user_id AND uj.job_id = a.job_id
            WHERE a.user_id = ? AND a.status = 'shortlisted' {skip}
            ORDER BY s.score DESC, COALESCE(uj.prescore, -1) DESC LIMIT ?""", (user_id, limit)).fetchall()
    return [r["id"] for r in rows]


@dataclass
class Drafter:
    user_id: int
    prefs: object
    facts: object
    stats: object
    room: int = 0
    done: set[int] = field(default_factory=set)
    budget: Budget | None = None


def draft_round_robin(conn, drafters: list[Drafter], llm, cfg, now: datetime,
                      heartbeat: Callable[[], None] = lambda: None) -> str | None:
    b = cfg.budgets
    share = b.global_drafts_per_day // share_divisor(conn, "draft", len(drafters))
    for d in drafters:
        d.budget = Budget(conn, d.user_id, {"draft": Limit("day", b.global_drafts_per_day, share)}, app_now(now))
        d.room = min(b.draft_per_run, max(0, share - int(d.budget.used("draft"))))
    active = [d for d in drafters if d.room > 0]
    stop: str | None = None
    while active and stop is None:
        for d in list(active):
            ids = apps_needing_drafts(conn, d.user_id, min(b.draft_batch, d.room), d.done)
            if not ids:
                active.remove(d)
                continue
            for app_id in ids:
                if not d.budget.take("draft"):  # spent up front, refunded below when no draft came back
                    active.remove(d)
                    break
                d.done.add(app_id)
                try:
                    draft_application(conn, app_id, llm, d.facts, d.prefs, now)
                except (LLMQuotaExceeded, LLMUnavailable) as e:
                    d.budget.refund("draft")
                    d.stats.errors.append(f"drafting stopped: {e}")
                    stop = "quota" if isinstance(e, LLMQuotaExceeded) else "unavailable"
                    break
                except LLMError as e:
                    d.budget.refund("draft")
                    d.stats.errors.append(f"draft application {app_id}: {e}")
                    continue
                d.room -= 1
                d.stats.drafted += 1
            heartbeat()
            if stop:
                break
            if d in active and d.room <= 0:
                active.remove(d)
    return stop
