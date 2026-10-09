from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from jobseeker.db import queries
from jobseeker.db.applications import (
    can_undo, get_status, mark_not_interested, set_notes, snooze, transition, undo_last_status,
)
from jobseeker.status import InvalidTransition
from jobseeker.web import oauth
from jobseeker.web.deps import current_facts, current_prefs, current_user, get_conn, render

router = APIRouter(prefix="/applications")


def _back(app_id: int, next_: str | None = None, *, msg: str | None = None, err: str | None = None,
          reconnect: bool = False):
    local = oauth.local_path(next_) is not None
    target = next_ if local else f"/applications/{app_id}"
    if msg or err:
        sep = "&" if "?" in target else "?"
        target += f"{sep}{'msg' if msg else 'err'}={quote(msg or err)}"
    if reconnect:  # the flash offers Reconnect Gmail, which comes back to this page
        target += f"{'&' if '?' in target else '?'}reconnect=1"
    return RedirectResponse(target, status_code=303)


@router.get("/{app_id}")
def detail(request: Request, app_id: int, user=Depends(current_user), prefs=Depends(current_prefs),
           facts=Depends(current_facts), conn=Depends(get_conn)):
    d = queries.application_detail(conn, user.id, app_id)
    if not d:
        raise HTTPException(404)
    terms = facts.skills if facts else []
    jd = (d["job"]["jd_text"] or "").lower()
    matched = sum(1 for t in terms if t and t.lower() in jd)
    from jobseeker.web.contacts import card_context

    from jobseeker.web.view import factor_bars, next_step, timeline

    ctx = card_context(request, conn, app_id, prefs)
    bars = factor_bars(d["score"]["breakdown"], request.app.state.rubric) if d["score"] else []
    return render(request, conn, "application.html", terms=terms, matched_skills=matched,
                  can_undo=can_undo(conn, app_id), bars=bars,
                  step=next_step(d["app"]["status"], bool(ctx["people"])),
                  timeline_items=timeline(d["events"]), **ctx, **d)


@router.post("/{app_id}/status")
def set_status(app_id: int, status: str = Form(...), next: str = Form(""), conn=Depends(get_conn)):
    try:
        transition(conn, app_id, status)
    except InvalidTransition as e:
        return _back(app_id, next, err=f"Can't move: {e}")
    return _back(app_id, next, msg=f"Marked {status.replace('_', ' ')}")


@router.post("/{app_id}/snooze")
def snooze_route(app_id: int, next: str = Form(""), conn=Depends(get_conn)):
    try:
        snooze(conn, app_id, datetime.now(UTC) + timedelta(days=3))
    except InvalidTransition as e:
        return _back(app_id, next, err=str(e))
    return _back(app_id, next, msg="Snoozed for 3 days")


@router.post("/{app_id}/notes")
def notes(app_id: int, notes: str = Form(""), conn=Depends(get_conn)):
    set_notes(conn, app_id, notes)
    return _back(app_id, msg="Notes saved")


@router.post("/{app_id}/undo")
def undo(app_id: int, next: str = Form(""), conn=Depends(get_conn)):
    was = get_status(conn, app_id)
    try:
        restored = undo_last_status(conn, app_id)
    except InvalidTransition as e:
        return _back(app_id, next, err=f"Can't undo: {e}")
    msg = f"Undone: back to {restored.replace('_', ' ')}"
    if was == "approved":
        msg += ". The Gmail draft still exists; delete it in Gmail"
    return _back(app_id, next, msg=msg)


@router.post("/{app_id}/not-interested")
def not_interested(app_id: int, block_company: bool = Form(False), conn=Depends(get_conn)):
    try:
        mark_not_interested(conn, app_id, block_company)
    except InvalidTransition as e:
        return _back(app_id, err=str(e))
    return _back(app_id, msg="Marked not interested" + (" and blocked the company" if block_company else ""))
