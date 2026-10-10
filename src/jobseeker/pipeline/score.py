"""Stage 6: score in batches of N per user, round-robin, inside each user's daily share and the global cap."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from jobseeker.clock import app_now
from jobseeker.db.applications import ensure_application, get_status, transition
from jobseeker.db.jobs import job_from_row, jobs_needing_score, save_score
from jobseeker.db.usage import Budget, Limit
from jobseeker.llm import LLMError, LLMQuotaExceeded, LLMUnavailable
from jobseeker.pipeline.eligible import active_users, share_divisor
from jobseeker.scoring.scorer import score_job


@dataclass
class UserStats:
    evaluated: int = 0
    filtered: int = 0
    below_cutoff: int = 0
    candidates: int = 0
    scored: int = 0
    shortlisted: int = 0
    drafted: int = 0
    score_share_left: int = 0
    stopped_by: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class Scorer:
    user_id: int
    prefs: object
    facts: object
    profile_hash: str
    stats: UserStats
    force: bool = False
    room: int = 0
    cap_reason: str = "share"
    done: set[int] = field(default_factory=set)
    budget: Budget | None = None


def _prepare(conn, scorers: list[Scorer], cfg, now: datetime) -> int:
    """Each user's room, and the run's pool: what's left of the global cap after holding a first-scores floor for
    every eligible user outside this run who hasn't scored today, so one user's run never leaves a new user nothing.
    The pool is one counter for the whole run (ruling by manager), so the users in it can't jointly eat the reserve.
    Sorts `scorers` in place: users with no scores today go first."""
    b = cfg.budgets
    share = b.global_scores_per_day // share_divisor(conn, "score", len(scorers))
    for s in scorers:
        s.budget = Budget(conn, s.user_id, {"score": Limit("day", b.global_scores_per_day, share)}, app_now(now))
        left = max(0, share - int(s.budget.used("score")))
        s.room = min(b.score_per_run, left)
        s.cap_reason = "run_cap" if b.score_per_run < left else "share"
        s.stats.score_share_left = left
    if not scorers:
        return 0
    scorers.sort(key=lambda s: s.budget.used("score") > 0)  # stable
    limits, in_run = scorers[0].budget.limits, {s.user_id for s in scorers}
    waiting = [u for u in active_users(conn)
               if u.id not in in_run and Budget(conn, u.id, limits, app_now(now)).used("score") == 0]
    reserved = min(b.score_per_run, share) * len(waiting)
    return max(0, int(b.global_scores_per_day - scorers[0].budget.used_all("score")) - reserved)


def score_round_robin(conn, scorers: list[Scorer], llm, rubric, cfg, now: datetime,
                      heartbeat: Callable[[], None] = lambda: None) -> str | None:
    pool = _prepare(conn, scorers, cfg, now)
    active = []
    for s in scorers:
        if s.room > 0:
            active.append(s)
        else:
            s.stats.stopped_by = "share"
    stop: str | None = None
    while active and stop is None:
        for s in list(active):
            n = min(cfg.budgets.score_batch, s.room)
            rows = jobs_needing_score(conn, s.user_id, rubric.version, n, force=s.force, with_jd=True,
                                      profile_hash=s.profile_hash, exclude=s.done)
            if not rows:
                s.stats.stopped_by = "no_candidates"
                active.remove(s)
                continue
            for row in rows:
                if pool <= 0:  # the rest of today's cap is held for users who haven't scored yet
                    stop = s.stats.stopped_by = "reserved"
                    break
                if not s.budget.take("score"):  # spent up front, refunded below when no score came back
                    stop = "global_cap" if s.budget.used_all("score") + 1 > s.budget.limits["score"].global_cap \
                        else None
                    s.stats.stopped_by = stop or "share"
                    break
                s.done.add(row["id"])
                try:
                    result = score_job(llm, job_from_row(row), s.facts, s.prefs, rubric, cfg.models.scoring)
                except LLMQuotaExceeded as e:
                    s.budget.refund("score")
                    stop = "quota"
                    s.stats.errors.append(f"scoring stopped: {e}")
                    break
                except LLMUnavailable as e:
                    s.budget.refund("score")
                    stop = "unavailable"
                    s.stats.errors.append(f"scoring stopped: {e}")
                    break
                except LLMError as e:
                    s.budget.refund("score")
                    s.stats.errors.append(f"score job {row['id']}: {e}")
                    continue
                except BaseException:
                    s.budget.refund("score")
                    raise
                model = getattr(llm, "last_model", None) or cfg.models.scoring
                save_score(conn, s.user_id, row["id"], result, model, rubric.version, row["jd_hash"],
                           profile_hash=s.profile_hash)
                s.room -= 1
                pool -= 1
                s.stats.scored += 1
                s.stats.score_share_left -= 1
                app_id = ensure_application(conn, s.user_id, row["id"], now)
                if result.recommendation == "apply" and get_status(conn, app_id) == "new":
                    transition(conn, app_id, "shortlisted", {"score": result.score}, now)
                    s.stats.shortlisted += 1
            heartbeat()
            if stop:
                break
            if s.stats.stopped_by:
                active.remove(s)
            elif s.room <= 0:
                s.stats.stopped_by = s.cap_reason
                active.remove(s)
    if stop:
        for s in scorers:
            if not s.stats.stopped_by or s in active:
                s.stats.stopped_by = stop
    return stop
