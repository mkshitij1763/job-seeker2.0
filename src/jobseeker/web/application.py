from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from jobseeker.db import queries
from jobseeker.db.users import OWNER_ID
from jobseeker.db.core import utcnow
from jobseeker.db.applications import (
    BlockedContact, can_undo, get_status, mark_not_interested, record_followup, save_contact, save_draft,
    set_gmail_draft_id, set_notes, snooze, transition, undo_last_status,
)
from jobseeker.gmail.client import GmailUnavailable, create_draft
from jobseeker.gmail.mime import build_raw_message
from jobseeker.llm import LLMError
from jobseeker.outreach.drafter import greeting, signature
from jobseeker.pipeline.run import draft_application
from jobseeker.profile.facts import load_facts
from jobseeker.status import InvalidTransition
from jobseeker.web.deps import get_conn, render

router = APIRouter(prefix="/applications")
KINDS = {"email", "li_note", "li_dm"}
REGENERATABLE = {"new", "shortlisted", "drafted", "approved"}


def _back(app_id: int, next_: str | None = None, *, msg: str | None = None, err: str | None = None):
    local = next_ and next_.startswith("/") and not next_.startswith(("//", "/\\"))  # "//host" leaves the site
    target = next_ if local else f"/applications/{app_id}"
    if msg or err:
        sep = "&" if "?" in target else "?"
        target += f"{sep}{'msg' if msg else 'err'}={quote(msg or err)}"
    return RedirectResponse(target, status_code=303)


@router.get("/{app_id}")
def detail(request: Request, app_id: int, conn=Depends(get_conn)):
    d = queries.application_detail(conn, OWNER_ID, app_id)
    if not d:
        raise HTTPException(404)
    settings = request.app.state.settings
    terms = load_facts(settings.facts_path).skills if settings.facts_path.exists() else []
    jd = (d["job"]["jd_text"] or "").lower()
    matched = sum(1 for t in terms if t and t.lower() in jd)
    from jobseeker.web.contacts import card_context

    from jobseeker.web.view import factor_bars, next_step, timeline

    ctx = card_context(request, conn, app_id)
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
        return _back(app_id, msg="Saved. Approving again creates a new Gmail draft; delete the older one in Gmail")
    return _back(app_id, msg="Draft saved")


@router.post("/{app_id}/draft")
def draft_now(request: Request, app_id: int, conn=Depends(get_conn)):
    state = request.app.state
    status = get_status(conn, app_id)
    if status not in REGENERATABLE:
        return _back(app_id, err=f"Can't regenerate drafts once {status.replace('_', ' ')}; edit them instead")
    try:
        facts = load_facts(state.settings.facts_path)
        draft_application(conn, app_id, state.llm_factory(), facts, state.prefs)
    except FileNotFoundError:
        return _back(app_id, err="No resume facts yet. Run `jobseeker init`")
    except LLMError as e:
        return _back(app_id, err=f"Drafting failed: {e}")
    if status == "approved":
        transition(conn, app_id, "drafted", {"reason": "regenerated after approval"})
        return _back(app_id, msg="Drafts regenerated. Approving again creates a new Gmail draft; "
                                 "delete the older one in Gmail")
    return _back(app_id, msg="Drafts generated")


@router.post("/{app_id}/approve")
async def approve(request: Request, app_id: int, conn=Depends(get_conn)):
    form = await request.form()  # the confirm_<rank> boxes are dynamic, so read the form here, then work off-loop
    return await run_in_threadpool(_approve, request.app.state, conn, app_id, form)


def _approve(state, conn, app_id: int, form):
    from jobseeker.db.contacts_repo import people

    d = queries.application_detail(conn, OWNER_ID, app_id)
    if not d:
        raise HTTPException(404)
    email = d["drafts"].get("email")
    if not email:
        return _back(app_id, err="No email draft yet")
    if get_status(conn, app_id) != "drafted":
        return _back(app_id, err=f"Can't approve from status '{get_status(conn, app_id)}'")
    everyone = people(conn, app_id)
    if not everyone:
        return _approve_single(state, conn, app_id, d, email, bool(form.get("confirm_unverified")))
    linked = [p for p in everyone if p["wave"] == 1]
    manual = d["contact"]  # "Add someone myself" while people are linked: emailed now too, as rank 0
    if manual and manual["id"] not in {p["contact_id"] for p in everyone}:
        linked.append({"rank": 0, "name": manual["name"] or manual["email"], "email": manual["email"],
                       "email_status": manual["email_status"], "contact_id": manual["id"]})
    if not linked:
        return _back(app_id, err="No one to email now: #1 and #2 were removed. Add someone yourself or run "
                                 "Find contacts again")
    targets, skipped = [], []
    for p in linked:
        if not p["email"] or p["email_status"] == "bounced":
            skipped.append(p["name"])
        elif p["email_status"] != "verified" and not form.get(f"confirm_{p['rank']}"):
            return _back(app_id, err=f"{p['name']}'s email is unverified. Tick the confirmation box to draft anyway")
        else:
            targets.append(p)
    if not targets:
        return _back(app_id, err="No usable email for #1 or #2. Edit the people or add an email first")
    created, failure, first_draft_id = [], None, None
    for p in targets:
        try:
            draft_id = create_draft(state.gmail_factory(), _raw_for(state, p["email"], p["name"], email))
        except GmailUnavailable as e:
            failure = e
            break
        if p["rank"]:
            conn.execute("""UPDATE application_contacts SET gmail_draft_id = ?, emailed_at = ?
                            WHERE application_id = ? AND rank = ?""", (draft_id, utcnow(), app_id, p["rank"]))
        conn.commit()
        created.append(p["name"])
        first_draft_id = first_draft_id or draft_id
    if created:
        set_gmail_draft_id(conn, app_id, first_draft_id)
        transition(conn, app_id, "approved", {"drafts_for": created})
    parts = [f"Gmail drafts created for {', '.join(created)}"] if created else []
    if skipped:
        parts.append(f"skipped {', '.join(skipped)} (no usable email)")
    if failure:
        return _back(app_id, err="; ".join(parts + [f"Gmail draft not created: {failure}"]))
    return _back(app_id, msg="; ".join(parts) + ". Review and press Send in Gmail")


def _raw_for(state, to: str, name: str, email: dict, extra: str = "") -> str:
    prefs = state.prefs
    body = email["body"] + (f"\n\n{extra}" if extra else "")
    return build_raw_message(
        to=to, subject=email["subject"], body=greeting(name, body) + signature(prefs),
        attachment=state.settings.resume_path if state.settings.resume_path.exists() else None,
        attachment_name=f"{prefs.name.replace(' ', '_')}_Resume.pdf")


def _approve_single(state, conn, app_id: int, d: dict, email: dict, confirm_unverified: bool):
    contact = d["contact"]
    if not contact or not contact["email"]:
        return _back(app_id, err="Add the contact's email first")
    if contact["email_status"] == "bounced":
        return _back(app_id, err="This email bounced before. Find another address")
    if contact["email_status"] != "verified" and not confirm_unverified:
        return _back(app_id, err="Email is unverified. Tick the confirmation box to draft anyway")
    try:
        draft_id = create_draft(state.gmail_factory(), _raw_for(state, contact["email"], contact["name"], email))
    except GmailUnavailable as e:
        return _back(app_id, err=f"Gmail draft not created: {e}")
    previous = email["gmail_draft_id"]
    set_gmail_draft_id(conn, app_id, draft_id)
    transition(conn, app_id, "approved", {"gmail_draft_id": draft_id})
    if previous:
        return _back(app_id, msg="New Gmail draft created. Delete the older draft for this contact in Gmail, "
                                 "then review and press Send")
    return _back(app_id, msg="Gmail draft created. Review and press Send in Gmail")


@router.post("/{app_id}/followed-up")
def followed_up(app_id: int, conn=Depends(get_conn)):
    try:
        record_followup(conn, app_id)
    except ValueError as e:
        return _back(app_id, err=str(e))
    return _back(app_id, msg="Follow-up recorded")


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
