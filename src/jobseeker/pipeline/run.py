from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

import httpx

from jobseeker.config import Preferences, Rubric
from jobseeker.db.applications import (
    blocked_companies, ensure_application, get_application, get_status, save_draft, set_suggestion,
    transition, wake_snoozed,
)
from jobseeker.db.companies import bump_jobs_seen, mark_inactive
from jobseeker.db.jobs import (
    expire_unscored, get_job, get_user_job, job_from_row, jobs_missing_prescore, jobs_needing_score, save_score,
    set_filter_reason,
    record_jd_attempt, set_jd_text, set_prescore, upsert_job,
)
from jobseeker.db.runs import finish_run, start_run
from jobseeker.llm import LLM, FallbackLLM, LLMError, LLMQuotaExceeded, LLMUnavailable
from jobseeker.outreach.drafter import draft_outreach
from jobseeker.pipeline.discovery import GENERIC_WORDS, discover
from jobseeker.pipeline.normalize import normalize, normalize_company, normalize_title
from jobseeker.pipeline.prefilter import prefilter
from jobseeker.pipeline.prescore import prescore
from jobseeker.profile.facts import Facts
from jobseeker.scoring.scorer import score_job

Describe = Callable[[str, str], str]
MAX_JD_ATTEMPTS = 2  # a LinkedIn job whose description failed twice waits to expire
MAX_CONSECUTIVE_FAILURES = 2  # stop fetching descriptions for the day after this many in a row


@dataclass
class RunStats:
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    filtered: int = 0
    below_cutoff: int = 0
    discovered: int = 0
    candidates: int = 0
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


def _rank(conn: sqlite3.Connection, user_id: int, stats: RunStats, job_id: int, facts: Facts, prefs: Preferences,
          cutoff: bool) -> None:
    """Store the job's pre-score for this user; with cutoff, set aside jobs below min_prescore."""
    row = get_job(conn, job_id)
    verdict = get_user_job(conn, user_id, job_id)
    if row is None or (verdict and verdict["filter_reason"] is not None):
        return
    points = prescore(job_from_row(row), facts, prefs)
    set_prescore(conn, user_id, job_id, points)
    if cutoff and points < prefs.min_prescore:
        set_filter_reason(conn, user_id, job_id, f"low pre-score: {points}")
        stats.below_cutoff += 1


def _fetch(conn, user_id: int, stats: RunStats, sources, client, facts: Facts, prefs: Preferences,
           now: datetime) -> None:
    blocked = blocked_companies(conn)
    known = {normalize_company(s.company.name) for s in sources if hasattr(s, "company")}
    seen: dict[str, tuple[str, set[str]]] = {}
    unrecorded: Counter[str] = Counter()  # jobs at companies discovery may record later this run
    for src in sources:
        try:
            raws = src.fetch(client)
        except Exception as e:  # one broken source must never kill the run
            stats.errors.append(f"{src.name}: {type(e).__name__}: {e}")
            norm = getattr(src, "discovered_as", None)
            if norm and isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                mark_inactive(conn, norm, now)
            continue
        stats.errors += [f"{src.name}: {w}" for w in getattr(src, "warnings", [])]
        stats.fetched += len(raws)
        for raw in raws:
            job = normalize(raw)
            if getattr(src, "discovers", False):
                seen.setdefault(normalize_company(job.company), (job.company, set()))[1].add(
                    normalize_title(job.title))
            job_id, is_new = upsert_job(conn, job, now)
            if is_new:
                stats.new += 1
                reason = prefilter(job, prefs, now, blocked)
                if reason:
                    set_filter_reason(conn, user_id, job_id, reason)
                    stats.filtered += 1
                    continue
                norm = normalize_company(job.company)
                if not bump_jobs_seen(conn, norm):
                    unrecorded[norm] += 1
            else:
                stats.duplicates += 1
            _rank(conn, user_id, stats, job_id, facts, prefs, cutoff=is_new)
    if client is not None and seen:
        query_words = {w for q in prefs.search.queries for w in normalize_title(q).split()}
        stats.discovered = discover(conn, client, seen, known | blocked, now,
                                    generic=GENERIC_WORDS | query_words)
        for norm, n in unrecorded.items():
            bump_jobs_seen(conn, norm, n)


def _select(conn, user_id: int, stats: RunStats, rubric: Rubric, facts: Facts, prefs: Preferences, now: datetime,
            force: bool, describe: Describe | None) -> list[dict]:
    expire_unscored(conn, user_id, now, prefs.max_age_days)
    for row in jobs_missing_prescore(conn, user_id):  # jobs stored before pre-scores existed
        _rank(conn, user_id, stats, row["id"], facts, prefs, cutoff=True)
    candidates = jobs_needing_score(conn, user_id, rubric.version, -1, force=force)
    stats.candidates = len(candidates)
    if describe is not None:  # rescore works offline from stored jobs
        _fill_linkedin_descriptions(conn, user_id, stats, candidates, facts, prefs, now, describe)
    # Score the best-ranked jobs that have a description; jobs still waiting for one never block the rest.
    return jobs_needing_score(conn, user_id, rubric.version, prefs.budgets.score_per_run, force=force, with_jd=True)


def _fill_linkedin_descriptions(conn, user_id: int, stats: RunStats, candidates: list[dict], facts: Facts, prefs: Preferences,
                                now: datetime, describe: Describe) -> None:
    cap = prefs.search.linkedin_descriptions_per_run
    blocked = blocked_companies(conn)
    attempts = failures = consecutive = 0
    last_error = ""
    for row in candidates:
        if attempts >= cap or consecutive >= MAX_CONSECUTIVE_FAILURES:
            break  # budget spent, or LinkedIn is probably blocking us today
        if row["source"] != "linkedin" or row["jd_text"].strip() or row["jd_attempts"] >= MAX_JD_ATTEMPTS:
            continue
        attempts += 1
        try:
            text = describe(row["source"], row["source_job_id"])
            error = "" if text else "empty description"
        except Exception as e:
            text, error = "", f"{type(e).__name__}: {e}"
        if not text:
            record_jd_attempt(conn, row["id"])
            failures, consecutive, last_error = failures + 1, consecutive + 1, error
            continue
        consecutive = 0
        set_jd_text(conn, row["id"], text)
        job = job_from_row(get_job(conn, row["id"]))
        reason = prefilter(job, prefs, now, blocked)  # the description may reveal 8+ years etc.
        if reason:
            set_filter_reason(conn, user_id, row["id"], reason)
            stats.filtered += 1
            continue
        _rank(conn, user_id, stats, row["id"], facts, prefs, cutoff=False)
    if failures:
        stats.errors.append(f"linkedin descriptions: {failures} failed (last: {last_error})")


def _run(conn, stats: RunStats, *, user_id: int, sources, client, llm: LLM, facts: Facts, prefs: Preferences,
         rubric: Rubric, now: datetime, fetch: bool, force_rescore: bool, describe: Describe) -> None:
    wake_snoozed(conn, now)
    if fetch:
        _fetch(conn, user_id, stats, sources, client, facts, prefs, now)

    quota_hit = unavailable = False
    for row in _select(conn, user_id, stats, rubric, facts, prefs, now, force_rescore, describe if fetch else None):
        try:
            result = score_job(llm, job_from_row(row), facts, prefs, rubric, prefs.models.scoring)
        except (LLMQuotaExceeded, LLMUnavailable) as e:
            stats.errors.append(f"scoring stopped: {e}")
            quota_hit = True
            unavailable = isinstance(e, LLMUnavailable)
            break
        except LLMError as e:
            stats.errors.append(f"score job {row['id']}: {e}")
            continue
        model = getattr(llm, "last_model", None) or prefs.models.scoring  # a fallback may have scored it
        save_score(conn, user_id, row["id"], result, model, rubric.version, row["jd_hash"])
        stats.scored += 1
        app_id = ensure_application(conn, user_id, row["id"], now)
        if result.recommendation == "apply" and get_status(conn, app_id) == "new":
            transition(conn, app_id, "shortlisted", {"score": result.score}, now)
            stats.shortlisted += 1

    # Scoring and drafting use different models (separate daily quotas): a used-up scoring quota only stops
    # drafting when they share one. Groq being unreachable stops both.
    same_model = prefs.models.drafting == prefs.models.scoring
    skip_drafting = (quota_hit and same_model) or unavailable
    drafting_apps = [] if skip_drafting else _apps_needing_drafts(conn, prefs.budgets.draft_per_run)
    for app_id in drafting_apps:
        try:
            draft_application(conn, app_id, llm, facts, prefs, now)
            stats.drafted += 1
        except (LLMQuotaExceeded, LLMUnavailable) as e:
            stats.errors.append(f"drafting stopped: {e}")
            break
        except LLMError as e:
            stats.errors.append(f"draft application {app_id}: {e}")


def run_daily(conn: sqlite3.Connection, *, user_id: int, sources, client, llm: LLM, facts: Facts, prefs: Preferences,
              rubric: Rubric, now: datetime | None = None, fetch: bool = True,
              force_rescore: bool = False,
              clock: Callable[[], datetime] = lambda: datetime.now(UTC),
              describe: Describe | None = None) -> RunStats:
    if describe is None:
        from jobseeker.sources.jobspy_source import fetch_description as describe
    llm = FallbackLLM(llm, prefs.models.fallbacks)
    now = now or clock()
    stats = RunStats()
    run_id = start_run(conn, now)
    try:
        _run(conn, stats, user_id=user_id, sources=sources, client=client, llm=llm, facts=facts, prefs=prefs, rubric=rubric,
             now=now, fetch=fetch, force_rescore=force_rescore, describe=describe)
    except Exception as e:  # the run log must always be closed
        stats.errors.append(f"run aborted: {type(e).__name__}: {e}")
    finally:
        data = asdict(stats)
        errors = data.pop("errors")
        finish_run(conn, run_id, data, errors, clock())
    return stats
