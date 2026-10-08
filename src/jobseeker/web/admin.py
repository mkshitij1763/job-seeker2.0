from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from jobseeker.db.users import LastAdmin, add_invite, list_invites, list_users, remove_invite, set_disabled
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
                  usage=usage_table(conn, datetime.now(UTC)))


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
