"""'Fetch now': the web only queues; the next tick (within 5 minutes) runs it."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from jobseeker.clock import app_now
from jobseeker.db import run_requests
from jobseeker.db.locks import held_since
from jobseeker.web.deps import current_user, get_conn

router = APIRouter(dependencies=[Depends(current_user)])


def fetch_now_state(conn, user_id: int, now: datetime, cfg) -> dict:
    req = run_requests.pending(conn, user_id)
    if req and req["status"] == "queued":
        return {"state": "queued", "text": "Queued, starts in a few minutes", "poll": True}
    if req and req["status"] == "running":
        since = app_now(datetime.fromisoformat(req["requested_at"])).strftime("%H:%M")
        return {"state": "running", "text": f"Running since {since}", "poll": True}
    last = run_requests.last_fetch_now_started(conn, user_id)
    if last:
        nxt = datetime.fromisoformat(last) + timedelta(hours=cfg.fetch_now.min_hours_between_per_user)
        if nxt > now:
            return {"state": "wait", "text": f"Next possible at {app_now(nxt).strftime('%H:%M')}", "poll": False}
    if run_requests.fetch_now_count_today(conn, now) >= cfg.fetch_now.max_per_day:
        return {"state": "used_up", "text": "Fetch now is used up for today", "poll": False}
    return {"state": "ready", "text": "", "poll": False}


def queue_if_allowed(conn, user_id: int, now: datetime, cfg) -> dict:
    """Check and queue in one write transaction, so concurrent POSTs (one user's double tap, or several users at the
    daily cap) can't all pass the check before any of them inserts. Returns the state seen; "ready" means queued."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        state = fetch_now_state(conn, user_id, now, cfg)
        if state["state"] != "ready":
            conn.rollback()
            return state
        run_requests.queue(conn, user_id, now)  # commits
        return state
    except sqlite3.IntegrityError:  # the one-pending-per-user index: another request of theirs got in first
        conn.rollback()
        return {"state": "queued", "text": "Queued, starts in a few minutes", "poll": True}
    except BaseException:
        conn.rollback()
        raise


def _back(request: Request, msg: str) -> RedirectResponse:
    target = request.headers.get("referer") or "/today"
    path = "/" + target.split("://", 1)[-1].split("/", 1)[-1] if "://" in target else target
    sep = "&" if "?" in path else "?"
    return RedirectResponse(f"{path.split('#')[0]}{sep}msg={quote(msg)}", status_code=303)


@router.post("/fetch-now")
def fetch_now(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    now = datetime.now(UTC)
    cfg = request.app.state.app_config
    state = queue_if_allowed(conn, user.id, now, cfg)
    if state["state"] in ("queued", "running"):
        return _back(request, "Already queued")
    if state["state"] in ("wait", "used_up"):
        return _back(request, state["text"])
    busy = held_since(conn, "run") is not None
    return _back(request, "Queued: starts after the current run" if busy else "Queued, starts in a few minutes")


@router.get("/fetch-now/status")
def status(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    s = fetch_now_state(conn, user.id, datetime.now(UTC), request.app.state.app_config)
    return request.app.state.templates.TemplateResponse(request, "_fetch_now.html", {"fetch_now": s})
