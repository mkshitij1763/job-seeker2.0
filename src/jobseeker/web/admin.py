from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from jobseeker.backup.nightly import recent_backups
from jobseeker.db.users import LastAdmin, add_invite, list_invites, list_users, remove_invite, set_disabled, set_outreach
from jobseeker.web.deps import get_conn, render, require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _back(msg: str = "", err: str = ""):
    q = f"?msg={quote(msg)}" if msg else (f"?err={quote(err)}" if err else "")
    return RedirectResponse(f"/admin{q}", 303)


def usage_table(conn, now: datetime) -> dict:
    periods = (now.strftime("%Y-%m-%d"), now.strftime("%Y-%m"))
    rows = conn.execute("SELECT user_id, service, amount FROM usage WHERE period IN (?, ?)", periods).fetchall()
    services = sorted({r["service"] for r in rows})
    by_user = {u["id"]: {"user": u, "values": {}} for u in list_users(conn)}
    for r in rows:
        if r["user_id"] in by_user:
            by_user[r["user_id"]]["values"][r["service"]] = r["amount"]
    return {"services": services, "rows": list(by_user.values())}


@router.get("")
def page(request: Request, conn=Depends(get_conn)):
    return render(request, conn, "admin.html", invites=list_invites(conn), users=list_users(conn),
                  usage=usage_table(conn, datetime.now(UTC)), backups=recent_backups(conn))


@router.post("/invites")
def invite(request: Request, email: str = Form(...), conn=Depends(get_conn)):
    if "@" not in email:
        return _back(err="Enter an email address")
    add_invite(conn, email, request.state.user.id, datetime.now(UTC))
    return _back(msg=f"Invited {email.strip().lower()}. Send them the link yourself")


@router.post("/invites/{email}/remove")
def uninvite(email: str, conn=Depends(get_conn)):
    remove_invite(conn, email)
    return _back(msg="Invite removed")


@router.post("/users/{user_id}/disable")
def disable(user_id: int, conn=Depends(get_conn)):
    try:
        set_disabled(conn, user_id, True, datetime.now(UTC))
    except LastAdmin as e:
        return _back(err=str(e))
    return _back(msg="User disabled and signed out")


@router.post("/users/{user_id}/enable")
def enable(user_id: int, conn=Depends(get_conn)):
    set_disabled(conn, user_id, False, datetime.now(UTC))
    return _back(msg="User enabled")


@router.post("/users/{user_id}/outreach")
def outreach(user_id: int, enabled: str = Form("0"), conn=Depends(get_conn)):
    target = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        return _back(err="No such user")
    on = enabled == "1"
    set_outreach(conn, user_id, on)
    if not on:
        return _back(msg="Outreach off. Their Gmail grant was removed; drafts and history stay hidden")
    return _back(msg=f"Outreach on. 1. Add {target['email']} as a test user in Google Cloud → OAuth consent screen. "
                     "2. Ask them to open Settings → Connect Gmail")
