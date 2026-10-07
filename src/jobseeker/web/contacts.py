from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request

from jobseeker.contacts import names
from jobseeker.contacts.finder import run_find
from jobseeker.db.contacts_repo import (
    find_state, get_domain, link_contact, next_candidate, people, set_find_status, upsert_contact,
)
from jobseeker.db.usage import Budget
from jobseeker.pipeline.normalize import normalize_company
from jobseeker.web.application import _back
from jobseeker.web.deps import get_conn

router = APIRouter(prefix="/applications")


def card_context(request: Request, conn, app_id: int) -> dict:
    state = request.app.state
    return {"people": people(conn, app_id), "find": find_state(conn, app_id, datetime.now(UTC)),
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
    if find_state(conn, app_id, datetime.now(UTC))["status"] == "running":
        return _back(app_id, msg="Already finding contacts")
    set_find_status(conn, app_id, "running")
    background.add_task(run_find, state.settings.db_path, app_id, state.prefs, deps_factory)
    return _back(app_id, msg="Finding contacts… this takes about half a minute")


@router.get("/{app_id}/contacts/card")
def card(request: Request, app_id: int, conn=Depends(get_conn)):
    app = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not app:
        raise HTTPException(404)
    drafts = {r["kind"]: dict(r) for r in conn.execute("SELECT * FROM drafts WHERE application_id = ?", (app_id,))}
    return request.app.state.templates.TemplateResponse(
        request, "_people.html", {"app": dict(app), "drafts": drafts, **card_context(request, conn, app_id)})


@router.post("/{app_id}/contacts/{rank}/remove")
def remove(app_id: int, rank: int, conn=Depends(get_conn)):
    nxt = next_candidate(conn, app_id)
    conn.execute("DELETE FROM application_contacts WHERE application_id = ? AND rank = ?", (app_id, rank))
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
