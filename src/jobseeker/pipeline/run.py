"""The daily run, for everyone: fetch once, then evaluate, describe, score and draft per user, fairly."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from jobseeker.db.locks import LockLost
from jobseeker.db.run_requests import INTERRUPTED
from jobseeker.db.runs import finish_run, start_run
from jobseeker.llm import FallbackLLM
from jobseeker.pipeline.describe import describe_shared
from jobseeker.pipeline.discovery import GENERIC_WORDS
from jobseeker.pipeline.draft import Drafter, draft_round_robin
from jobseeker.pipeline.eligible import drafts_enabled
from jobseeker.pipeline.evaluate import evaluate
from jobseeker.pipeline.fetch import FetchStats, fetch_shared
from jobseeker.pipeline.normalize import normalize_title
from jobseeker.pipeline.plan import build_plan, plan_users
from jobseeker.pipeline.profile_hash import profile_hash
from jobseeker.pipeline.score import Scorer, UserStats, score_round_robin
from jobseeker.db.jobs import linkedin_picks
from jobseeker.sources.registry import build_sources

ALERT_NOTE = "Couldn't send the match alert"
NO_FACTS = "No resume facts yet, so nothing was scored"
BOARD_FRESH = timedelta(hours=12)  # Fetch now skips ATS boards fetched OK this recently


@dataclass
class RunReport:
    fetch_run_id: int | None = None
    fetch: FetchStats | None = None
    users: dict[int, UserStats] = field(default_factory=dict)
    aborted: str | None = None
    user_runs: dict[int, int] = field(default_factory=dict)  # user id -> their kind='user' run


def _default_notify(conn, user_id, started, now):
    from jobseeker.push.notify import notify_new_matches
    return notify_new_matches(conn, user_id, started, now)


STARVED = {"global_cap", "quota", "reserved"}  # scoring stopped by the shared allowance, not the user's own share


def _default_notify_done(conn, user_id, started, now, stats):
    from jobseeker.push.notify import notify_run_finished
    return notify_run_finished(conn, user_id, started, now, scored=stats.scored,
                               starved=stats.stopped_by in STARVED)


def _custom_and_updated(conn, user_id: int) -> tuple[str, str]:
    row = conn.execute("SELECT json_extract(data, '$.custom_role') AS c, updated_at FROM user_prefs WHERE user_id = ?",
                       (user_id,)).fetchone()
    return ((row["c"] or ""), row["updated_at"]) if row else ("", "")


def run_all(conn, *, users, trigger: str, fetch: bool, plan_cap: int, client, llm, cfg, rubric, now: datetime,
            companies=(), describe=None, sources_factory=build_sources, context=None,
            notify=_default_notify, notify_done=_default_notify_done, force_users: frozenset[int] = frozenset(),
            heartbeat: Callable[[], None] = lambda: None,
            clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> RunReport:
    if describe is None:
        from jobseeker.sources.jobspy_source import fetch_description as describe
    llm = FallbackLLM(llm, cfg.models.fallbacks)  # one chain for the whole run
    if context is None:
        from jobseeker.db.profile import load_user_context
        context = lambda c, uid: load_user_context(c, uid, cfg)  # noqa: E731
    report = RunReport(users={u.id: UserStats() for u in users})
    user_runs = report.user_runs
    contexts: dict[int, tuple] = {}
    try:
        for u in users:
            prefs, facts = context(conn, u.id)
            if facts is None:
                report.users[u.id].errors.append(NO_FACTS)
            else:
                contexts[u.id] = (prefs, facts)
        if fetch:
            from jobseeker.db.companies import active_companies, fresh_boards
            run_no = conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'fetch'").fetchone()[0]
            report.fetch_run_id = start_run(conn, now, None, kind="fetch", trigger=trigger)
            report.fetch = FetchStats()
            catalog = {r.query for r in cfg.roles}
            planners = plan_users([(uid, p, *_custom_and_updated(conn, uid)) for uid, (p, _) in contexts.items()])
            plan = build_plan(planners, list(cfg.search.sites), catalog, run_no, plan_cap, cfg.search.max_custom_queries)
            fs = report.fetch
            fs.searches_planned, fs.searches_trimmed, fs.searches_total = plan.planned, plan.trimmed, plan.total
            words = GENERIC_WORDS | {w for q in plan.linkedin + [q for q, _ in plan.pairs] for w in normalize_title(q).split()}
            sources = sources_factory(list(companies), active_companies(conn), cfg.search, plan)
            if trigger == "fetch_now":  # the scheduled run still sweeps every board
                fresh = fresh_boards(conn, now - BOARD_FRESH)
                sources = [s for s in sources if not (hasattr(s, "company") and s.name in fresh)]
            fetch_shared(conn, sources, client, now, words, report.fetch, heartbeat)
        for u in users:
            user_runs[u.id] = start_run(conn, now, u.id, kind="user", trigger=trigger, parent_id=report.fetch_run_id)
        for uid, (prefs, facts) in contexts.items():
            ev = evaluate(conn, uid, prefs, facts, now, heartbeat)
            st = report.users[uid]
            st.evaluated, st.filtered, st.below_cutoff = ev.evaluated, ev.filtered, ev.below_cutoff
        if fetch and contexts:
            cap = cfg.search.linkedin_descriptions_per_run
            d = describe_shared(conn, [linkedin_picks(conn, uid, cap) for uid in contexts], cap, describe, heartbeat)
            report.fetch.described = d.described
            report.fetch.errors += d.errors
            for uid, (prefs, facts) in contexts.items():
                evaluate(conn, uid, prefs, facts, now, heartbeat)  # picks up changed jd_hash only
        scorers = [Scorer(uid, p, f, profile_hash(p, f), report.users[uid], force=uid in force_users)
                   for uid, (p, f) in contexts.items()]
        stop = score_round_robin(conn, scorers, llm, rubric, cfg, now, heartbeat)
        if trigger in ("schedule", "fetch_now", "onboarding"):  # the daily alert; "your search finished" otherwise
            for uid in contexts:
                started = conn.execute("SELECT started_at FROM runs WHERE id = ?", (user_runs[uid],)).fetchone()[0]
                try:
                    note = notify(conn, uid, datetime.fromisoformat(started), now) if trigger == "schedule" \
                        else notify_done(conn, uid, datetime.fromisoformat(started), now, report.users[uid])
                except Exception:
                    note = ALERT_NOTE
                if note:
                    report.users[uid].errors.append(note)
        same_model = cfg.models.drafting == cfg.models.scoring
        if not (stop == "unavailable" or (stop == "quota" and same_model)):
            eligible = [u for u in users if u.id in contexts and drafts_enabled(u)]
            drafters = [Drafter(u.id, *contexts[u.id], report.users[u.id]) for u in eligible]
            draft_round_robin(conn, drafters, llm, cfg, now, heartbeat)
    except LockLost:
        report.aborted = "run superseded"
    except SystemExit:  # SIGTERM (cli.py turns it into SystemExit): close the run log below, then let the exit go on
        report.aborted = INTERRUPTED
        raise
    except Exception as e:  # the run log must always be closed
        report.aborted = f"run aborted: {type(e).__name__}: {e}"
    finally:
        end = clock()
        if report.fetch_run_id is not None:
            data = asdict(report.fetch)
            errors = data.pop("errors") + ([report.aborted] if report.aborted else [])
            finish_run(conn, report.fetch_run_id, data, errors, end)
        for uid, run_id in user_runs.items():
            data = asdict(report.users[uid])
            errors = data.pop("errors") + ([report.aborted] if report.aborted else [])
            finish_run(conn, run_id, data, errors, end)
    return report
