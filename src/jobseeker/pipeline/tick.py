"""The only host hook: run every 5 minutes. The schedule, catch-up, Fetch now and the nightly backup live here."""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from jobseeker.backup.nightly import nightly_backup
from jobseeker.clock import app_now, app_today, day_start_utc
from jobseeker.db import run_requests
from jobseeker.db.applications import wake_snoozed
from jobseeker.db.core import iso
from jobseeker.db.locks import acquire, release
from jobseeker.db.users import user_by_id
from jobseeker.pipeline.eligible import active_users

log = logging.getLogger(__name__)


def scheduled_due(conn, cfg, now: datetime) -> bool:
    local = app_now(now)
    if local.time() < cfg.schedule.daily_time():
        return False
    since = iso(day_start_utc(app_today(now)))
    rows = conn.execute("SELECT finished_at FROM runs WHERE kind = 'fetch' AND trigger = 'schedule' AND started_at >= ?",
                        (since,)).fetchall()
    if any(r["finished_at"] for r in rows):
        return False
    return len(rows) < cfg.schedule.max_attempts_per_day


def ping(url: str, ok: bool, get=httpx.get) -> None:
    if not url:
        return
    try:
        get(url if ok else url.rstrip("/") + "/fail", timeout=5.0)
    except Exception as e:  # a dead pinger must never fail the tick
        log.warning("health ping failed: %s", e)


def tick(conn, *, settings, cfg, now: datetime, run, backup=nightly_backup, ping_fn=None, holder: str) -> str:
    wake_snoozed(conn, now)
    if not acquire(conn, "run", holder, now, cfg.lock.takeover_after_minutes):
        return "busy"
    try:
        run_requests.fail_stuck(conn, now, cfg.lock.takeover_after_minutes)
        if scheduled_due(conn, cfg, now):
            report = run("schedule", active_users(conn), cfg.search.max_searches_per_run)
            try:
                result = backup(conn, settings, now)
                backup_ok = result.ok
            except Exception as e:
                log.error("backup failed: %s", e)
                backup_ok = False
            ok = report.aborted is None and backup_ok
            (ping_fn or (lambda url, good: ping(url, good)))(getattr(settings, "healthcheck_ping_url", ""), ok)
            return "scheduled"
        req = run_requests.next_queued(conn)
        if req:
            if run_requests.fetch_now_count_today(conn, now, include_queued=False) >= cfg.fetch_now.max_per_day:
                run_requests.mark(conn, req["id"], "failed", now)  # queued past the cap: never run it
                return "fetch_now_refused"
            run_requests.mark(conn, req["id"], "running", now)
            user = user_by_id(conn, req["user_id"])
            try:
                report = run("fetch_now", [user], cfg.search.max_searches_fetch_now)
            except SystemExit:  # SIGTERM mid-run: fail the request now (the user sees why), then release the lock
                rid = conn.execute("SELECT MAX(id) FROM runs WHERE kind = 'fetch' AND trigger = 'fetch_now' "
                                   "AND started_at >= ?", (iso(now),)).fetchone()[0]
                run_requests.mark(conn, req["id"], "failed", now, rid)
                raise
            run_requests.mark(conn, req["id"], "failed" if report.aborted else "done", now, report.fetch_run_id)
            return "fetch_now"
        return "idle"
    finally:
        release(conn, "run", holder)
