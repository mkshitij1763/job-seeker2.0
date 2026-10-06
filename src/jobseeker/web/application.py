from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from jobseeker.db import queries
from jobseeker.db.applications import (
    BlockedContact, get_status, mark_not_interested, record_followup, save_contact, save_draft,
    set_gmail_draft_id, set_notes, snooze, transition,
)
from jobseeker.gmail.client import GmailUnavailable, create_draft
from jobseeker.gmail.mime import build_raw_message
from jobseeker.llm import LLMError
from jobseeker.outreach.drafter import signature
from jobseeker.pipeline.run import draft_application
from jobseeker.profile.facts import load_facts
from jobseeker.status import InvalidTransition
from jobseeker.web.deps import get_conn, render

router = APIRouter(prefix="/applications")
KINDS = {"email", "li_note", "li_dm"}


def _back(app_id: int, next_: str | None = None, *, msg: str | None = None, err: str | None = None):
    target = next_ if next_ and next_.startswith("/") else f"/applications/{app_id}"
    if msg or err:
        sep = "&" if "?" in target else "?"
        target += f"{sep}{'msg' if msg else 'err'}={quote(msg or err)}"
    return RedirectResponse(target, status_code=303)


@router.get("/{app_id}")
def detail(request: Request, app_id: int, conn=Depends(get_conn)):
    d = queries.application_detail(conn, app_id)
    if not d:
        raise HTTPException(404)
    settings = request.app.state.settings
    terms = load_facts(settings.facts_path).skills if settings.facts_path.exists() else []
    return render(request, conn, "application.html", terms=terms, **d)


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


@router.post("/{app_id}/contact")
def contact(app_id: int, name: str = Form(""), role: str = Form(""), linkedin_url: str = Form(""),
            email: str = Form(""), email_status: str = Form("unverified"), conn=Depends(get_conn)):
    if email_status not in {"unverified", "verified", "bounced"}:
        return _back(app_id, err="Bad email status")
    try:
        save_contact(conn, app_id, name=name.strip(), role=role.strip(), linkedin_url=linkedin_url.strip(),
                     email=email.strip(), email_status=email_status)
    except BlockedContact as e:
        return _back(app_id, err=str(e))
    return _back(app_id, msg="Contact saved")


@router.post("/{app_id}/drafts/{kind}")
def edit_draft(app_id: int, kind: str, subject: str = Form(""), body: str = Form(...), conn=Depends(get_conn)):
    if kind not in KINDS:
        raise HTTPException(404)
    save_draft(conn, app_id, kind, subject, body, edited=True)
    if kind == "email" and get_status(conn, app_id) == "approved":
        transition(conn, app_id, "drafted", {"reason": "edited after approval"})
        return _back(app_id, msg="Saved. Approve again to update the Gmail draft")
    return _back(app_id, msg="Draft saved")


@router.post("/{app_id}/draft")
def draft_now(request: Request, app_id: int, conn=Depends(get_conn)):
    state = request.app.state
    try:
        facts = load_facts(state.settings.facts_path)
        draft_application(conn, app_id, state.llm_factory(), facts, state.prefs)
    except FileNotFoundError:
        return _back(app_id, err="No resume facts yet. Run `jobseeker init`")
    except LLMError as e:
        return _back(app_id, err=f"Drafting failed: {e}")
    return _back(app_id, msg="Drafts generated")


@router.post("/{app_id}/approve")
def approve(request: Request, app_id: int, confirm_unverified: bool = Form(False), conn=Depends(get_conn)):
    state = request.app.state
    d = queries.application_detail(conn, app_id)
    if not d:
        raise HTTPException(404)
    contact, email = d["contact"], d["drafts"].get("email")
    if not email:
        return _back(app_id, err="No email draft yet")
    if not contact or not contact["email"]:
        return _back(app_id, err="Add the contact's email first")
    if contact["email_status"] == "bounced":
        return _back(app_id, err="This email bounced before. Find another address")
    if contact["email_status"] != "verified" and not confirm_unverified:
        return _back(app_id, err="Email is unverified. Tick the confirmation box to draft anyway")
    if get_status(conn, app_id) != "drafted":
        return _back(app_id, err=f"Can't approve from status '{get_status(conn, app_id)}'")
    prefs = state.prefs
    raw = build_raw_message(
        to=contact["email"], subject=email["subject"], body=email["body"] + signature(prefs),
        attachment=state.settings.resume_path if state.settings.resume_path.exists() else None,
        attachment_name=f"{prefs.name.replace(' ', '_')}_Resume.pdf")
    try:
        draft_id = create_draft(state.gmail_factory(), raw)
    except GmailUnavailable as e:
        return _back(app_id, err=f"Reconnect Gmail: {e}")
    set_gmail_draft_id(conn, app_id, draft_id)
    transition(conn, app_id, "approved", {"gmail_draft_id": draft_id})
    return _back(app_id, msg="Gmail draft created. Review and press Send in Gmail")


@router.post("/{app_id}/followed-up")
def followed_up(app_id: int, conn=Depends(get_conn)):
    try:
        record_followup(conn, app_id)
    except ValueError as e:
        return _back(app_id, err=str(e))
    return _back(app_id, msg="Follow-up recorded")


@router.post("/{app_id}/not-interested")
def not_interested(app_id: int, block_company: bool = Form(False), conn=Depends(get_conn)):
    try:
        mark_not_interested(conn, app_id, block_company)
    except InvalidTransition as e:
        return _back(app_id, err=str(e))
    return _back(app_id, msg="Marked not interested" + (" and blocked the company" if block_company else ""))
