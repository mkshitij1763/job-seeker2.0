from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from jobseeker.clock import app_now
from jobseeker.db import queries
from jobseeker.db.core import utcnow
from jobseeker.db.applications import (
    BlockedContact, get_status, record_followup, save_contact, save_draft, set_gmail_draft_id, transition,
)
from jobseeker.db.usage import Budget, outreach_limits
from jobseeker.db.gmail_tokens import mark_expired
from jobseeker.gmail.client import GmailUnavailable, create_draft
from jobseeker.gmail.mime import build_raw_message
from jobseeker.llm import LLMError
from jobseeker.outreach.drafter import greeting, signature
from jobseeker.pipeline.draft import draft_application
from jobseeker.profile.resume import resume_path
from jobseeker.web.application import _back
from jobseeker.web.deps import current_facts, current_prefs, current_user, get_conn

# Outreach routes (contacts, drafts, Gmail). app.py mounts this router behind require_outreach: 404 when off.
router = APIRouter(prefix="/applications")
KINDS = {"email", "li_note", "li_dm"}
REGENERATABLE = {"new", "shortlisted", "drafted", "approved"}


def gmail_failed(conn, user_id: int, app_id: int, e: GmailUnavailable, parts: list[str] | None = None):
    """Drafts already made stay named; an expired grant is marked and the flash offers Reconnect Gmail."""
    parts = list(parts or [])
    if e.reconnect:
        mark_expired(conn, user_id)
        return _back(app_id, err="; ".join(parts + ["Gmail needs reconnecting"]), reconnect=True)
    return _back(app_id, err="; ".join(parts + [f"Gmail draft not created: {e}"]))


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
def draft_now(request: Request, app_id: int, user=Depends(current_user), prefs=Depends(current_prefs),
              facts=Depends(current_facts), conn=Depends(get_conn)):
    state = request.app.state
    status = get_status(conn, app_id)
    if status not in REGENERATABLE:
        return _back(app_id, err=f"Can't regenerate drafts once {status.replace('_', ' ')}; edit them instead")
    if facts is None:
        return _back(app_id, err="No resume facts yet. Add your resume in Settings")
    budget = Budget(conn, user.id, outreach_limits(conn, prefs.contacts, state.app_config.budgets.global_drafts_per_day),
                    app_now())
    if not budget.take("draft"):
        return _back(app_id, err=budget.exhausted_note("draft", "drafting"))
    try:
        draft_application(conn, app_id, state.llm_factory(), facts, prefs)
    except LLMError as e:
        budget.refund("draft")
        return _back(app_id, err=f"Drafting failed: {e}")
    except BaseException:
        budget.refund("draft")
        raise
    if status == "approved":
        transition(conn, app_id, "drafted", {"reason": "regenerated after approval"})
        return _back(app_id, msg="Drafts regenerated. Approving again creates a new Gmail draft; "
                                 "delete the older one in Gmail")
    return _back(app_id, msg="Drafts generated")


@router.post("/{app_id}/approve")
async def approve(request: Request, app_id: int, user=Depends(current_user), prefs=Depends(current_prefs),
                  conn=Depends(get_conn)):
    form = await request.form()  # the confirm_<rank> boxes are dynamic, so read the form here, then work off-loop
    return await run_in_threadpool(_approve, request.app.state, conn, prefs, user.id, app_id, form)


def _approve(state, conn, prefs, user_id: int, app_id: int, form):
    from jobseeker.db.contacts_repo import people

    d = queries.application_detail(conn, user_id, app_id)
    if not d:
        raise HTTPException(404)
    email = d["drafts"].get("email")
    if not email:
        return _back(app_id, err="No email draft yet")
    if get_status(conn, app_id) != "drafted":
        return _back(app_id, err=f"Can't approve from status '{get_status(conn, app_id)}'")
    everyone = people(conn, app_id)
    if not everyone:
        return _approve_single(state, conn, prefs, user_id, app_id, d, email, bool(form.get("confirm_unverified")))
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
            draft_id = create_draft(state.gmail_factory(conn, user_id), _raw_for(state, prefs, user_id, p["email"], p["name"], email))
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
        return gmail_failed(conn, user_id, app_id, failure, parts)
    return _back(app_id, msg="; ".join(parts) + ". Review and press Send in Gmail")


def _raw_for(state, prefs, user_id: int, to: str, name: str, email: dict, extra: str = "") -> str:
    resume = resume_path(state.settings.jobseeker_home, user_id)
    body = email["body"] + (f"\n\n{extra}" if extra else "")
    return build_raw_message(
        to=to, subject=email["subject"], body=greeting(name, body) + signature(prefs),
        attachment=resume if resume.exists() else None,
        attachment_name=f"{prefs.name.replace(' ', '_')}_Resume.pdf")


def _approve_single(state, conn, prefs, user_id: int, app_id: int, d: dict, email: dict, confirm_unverified: bool):
    contact = d["contact"]
    if not contact or not contact["email"]:
        return _back(app_id, err="Add the contact's email first")
    if contact["email_status"] == "bounced":
        return _back(app_id, err="This email bounced before. Find another address")
    if contact["email_status"] != "verified" and not confirm_unverified:
        return _back(app_id, err="Email is unverified. Tick the confirmation box to draft anyway")
    try:
        draft_id = create_draft(state.gmail_factory(conn, user_id), _raw_for(state, prefs, user_id, contact["email"], contact["name"], email))
    except GmailUnavailable as e:
        return gmail_failed(conn, user_id, app_id, e)
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
