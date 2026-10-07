from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request

from jobseeker.contacts import names
from jobseeker.contacts.finder import run_find
from jobseeker.db.contacts_repo import (
    claim_find, emailed_count, find_state, get_domain, link_contact, next_candidate, people, third_due,
    upsert_contact,
)
from jobseeker.db.usage import Budget
from jobseeker.pipeline.normalize import normalize_company
from jobseeker.web.application import _back
from jobseeker.web.deps import get_conn

router = APIRouter(prefix="/applications")


def _company(conn, app_id: int) -> str:
    return conn.execute("SELECT j.company FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.id = ?",
                        (app_id,)).fetchone()["company"]


def card_context(request: Request, conn, app_id: int) -> dict:
    state = request.app.state
    return {"people": people(conn, app_id), "find": find_state(conn, app_id, datetime.now(UTC)),
            "domain": get_domain(conn, normalize_company(_company(conn, app_id))),
            "third_due": third_due(conn, app_id, datetime.now(UTC)),
            "already_emailed": emailed_count(conn, app_id) > 0,
            "usage": Budget(conn, state.prefs.contacts, datetime.now(UTC)).summary(),
            "has_tavily": bool(state.settings.tavily_api_key)}


@router.post("/{app_id}/contacts/find")
def find(request: Request, app_id: int, background: BackgroundTasks, conn=Depends(get_conn)):
    state = request.app.state
    if not state.settings.tavily_api_key and state.contacts_deps_factory is None:
        return _back(app_id, err="Add TAVILY_API_KEY to .env to find contacts")
    deps_factory = state.contacts_deps_factory
    probe = deps_factory()
    if probe.tavily is None:
        return _back(app_id, err="Add TAVILY_API_KEY to .env to find contacts")
    if emailed_count(conn, app_id):
        return _back(app_id, err="People were already emailed for this job; edit or remove them individually")
    if not claim_find(conn, app_id, datetime.now(UTC)):
        return _back(app_id, msg="Already finding contacts")
    background.add_task(run_find, state.settings.db_path, app_id, state.prefs, deps_factory)
    return _back(app_id)  # the People card shows progress and replaces itself when done


@router.get("/{app_id}/contacts/card")
def card(request: Request, app_id: int, conn=Depends(get_conn)):
    app = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not app:
        raise HTTPException(404)
    drafts = {r["kind"]: dict(r) for r in conn.execute("SELECT * FROM drafts WHERE application_id = ?", (app_id,))}
    return request.app.state.templates.TemplateResponse(
        request, "_people.html", {"app": dict(app), "drafts": drafts, **card_context(request, conn, app_id)})


@router.post("/{app_id}/contacts/domain")
def set_domain(app_id: int, domain: str = Form(""), conn=Depends(get_conn)):
    from jobseeker.db.contacts_repo import save_domain

    value = domain.strip().lower()
    value = value.split("://", 1)[-1].split("/", 1)[0].removeprefix("www.").lstrip("@")
    if "." not in value:
        return _back(app_id, err="Enter a domain like company.com")
    save_domain(conn, normalize_company(_company(conn, app_id)), domain=value, pattern=None, catch_all=None,
                mx_host=None)
    return _back(app_id, msg=f"Email domain set to {value}. Run Find contacts again to rebuild emails")


@router.post("/{app_id}/contacts/{rank}/remove")
def remove(app_id: int, rank: int, conn=Depends(get_conn)):
    nxt = next_candidate(conn, app_id)
    removed = conn.execute("SELECT contact_id FROM application_contacts WHERE application_id = ? AND rank = ?",
                           (app_id, rank)).fetchone()
    conn.execute("DELETE FROM application_contacts WHERE application_id = ? AND rank = ?", (app_id, rank))
    if removed:  # the app's main contact must never stay pointed at a removed person
        conn.execute("""UPDATE applications SET contact_id = (SELECT contact_id FROM application_contacts
                        WHERE application_id = ? ORDER BY rank LIMIT 1) WHERE id = ? AND contact_id = ?""",
                     (app_id, app_id, removed["contact_id"]))
    conn.commit()
    if not nxt:
        return _back(app_id, msg="Removed. No more candidates; run Find contacts again for more")
    company = conn.execute("SELECT j.company FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.id = ?",
                           (app_id,)).fetchone()["company"]
    dom = get_domain(conn, normalize_company(company)) or {}
    nm = names.clean_name(nxt["name"])
    email, source = "", ""
    if dom.get("domain") and nm:
        guesses = names.candidates(nm, dom["domain"], [dom["pattern"]] if dom.get("pattern") else [])
        email, source = (guesses[0], "pattern") if guesses else ("", "")
    cid = upsert_contact(conn, company, nxt["name"], nxt["headline"], nxt["linkedin_url"], email, "unverified")
    if cid is None:
        return _back(app_id, err=f"{nxt['name']} said not interested before; run Find contacts again")
    link_contact(conn, app_id, rank, cid, nxt["label"], nxt["reason"], source)
    return _back(app_id, msg=f"Replaced with {nxt['name']} (email is a pattern guess)")


@router.post("/{app_id}/contacts/{rank}/edit")
def edit(app_id: int, rank: int, name: str = Form(...), email: str = Form(""),
         email_status: str = Form("unverified"), conn=Depends(get_conn)):
    if email_status not in {"unverified", "verified", "bounced"}:
        return _back(app_id, err="Bad email status")
    row = conn.execute("SELECT contact_id FROM application_contacts WHERE application_id = ? AND rank = ?",
                       (app_id, rank)).fetchone()
    if not row:
        raise HTTPException(404)
    conn.execute("UPDATE contacts SET name = ?, email = ?, email_status = ? WHERE id = ?",
                 (name.strip(), email.strip(), email_status, row["contact_id"]))
    conn.execute("UPDATE application_contacts SET email_source = 'manual' WHERE application_id = ? AND rank = ?",
                 (app_id, rank))
    conn.commit()
    return _back(app_id, msg="Saved")


@router.post("/{app_id}/contacts/3/email")
def email_third(request: Request, app_id: int, conn=Depends(get_conn)):
    from jobseeker.db.applications import record_followup
    from jobseeker.db.core import utcnow
    from jobseeker.gmail.client import GmailUnavailable, create_draft
    from jobseeker.web.application import _raw_for

    if not third_due(conn, app_id, datetime.now(UTC)):
        return _back(app_id, err="Email #3 is offered 5 days after Mark sent with no reply")
    third = next((p for p in people(conn, app_id) if p["rank"] == 3), None)
    if not third or not third["email"] or third["email_status"] == "bounced" or third["emailed_at"]:
        return _back(app_id, err="No usable email for #3")
    email = conn.execute("SELECT * FROM drafts WHERE application_id = ? AND kind = 'email'", (app_id,)).fetchone()
    try:
        draft_id = create_draft(request.app.state.gmail_factory(),
                                _raw_for(request.app.state, third["email"], third["name"], dict(email),
                                         extra="I also reached out to your colleague earlier."))
    except GmailUnavailable as e:
        return _back(app_id, err=f"Gmail draft not created: {e}")
    conn.execute("UPDATE application_contacts SET gmail_draft_id = ?, emailed_at = ? WHERE application_id = ? AND rank = 3",
                 (draft_id, utcnow(), app_id))
    conn.commit()
    record_followup(conn, app_id)
    return _back(app_id, msg=f"Gmail draft created for {third['name']}. Review and press Send")
