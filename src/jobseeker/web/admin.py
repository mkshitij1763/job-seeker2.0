from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from jobseeker.backup.nightly import recent_backups
from jobseeker.clock import app_now
from jobseeker.db.profile import get_onboarding, get_user_prefs
from jobseeker.db.users import (LastAdmin, add_invite, is_tombstone, list_invites, list_users, remove_invite, set_disabled,
                                set_outreach)
from jobseeker.web.deps import get_conn, render, require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _back(msg: str = "", err: str = "", extra: str = ""):
    q = f"?msg={quote(msg)}" if msg else (f"?err={quote(err)}" if err else "")
    return RedirectResponse(f"/admin{q}{extra}", 303)


def _periods(now: datetime) -> tuple[str, str]:
    """Today and this month in app time (IST), the periods Budget writes usage under."""
    t = app_now(now)
    return t.strftime("%Y-%m-%d"), t.strftime("%Y-%m")


def usage_table(conn, now: datetime) -> dict:
    periods = _periods(now)
    rows = conn.execute("SELECT user_id, service, amount FROM usage WHERE period IN (?, ?)", periods).fetchall()
    services = sorted({r["service"] for r in rows})
    by_user = {u["id"]: {"user": u, "values": {},  # a deleted account's spend still counts toward today's caps
                         "label": f"Deleted account ({u['email'][8:-8]})" if is_tombstone(u) else u["email"]}
               for u in list_users(conn)}
    for r in rows:
        if r["user_id"] in by_user:
            by_user[r["user_id"]]["values"][r["service"]] = r["amount"]
    return {"services": services, "rows": list(by_user.values())}


@router.get("")
def page(request: Request, conn=Depends(get_conn)):
    invited = request.query_params.get("invited")
    return render(request, conn, "admin.html", invites=list_invites(conn),
                  users=[u for u in list_users(conn) if not is_tombstone(u)],
                  usage=usage_table(conn, datetime.now(UTC)), backups=recent_backups(conn),
                  invited=invited, app_link=request.app.state.settings.base_url if invited else "")


def _num(x) -> str:
    return "" if x is None else (f"{x:g}" if isinstance(x, float) else str(x))


def user_overview(conn, user_id: int, now: datetime) -> dict | None:
    """What the admin may see about one user: account, preferences, matching and application counts, usage.
    Never their resume, facts, Gmail grant, contacts or drafts."""
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or is_tombstone(dict(row)):
        return None
    _, onboarded_at = get_onboarding(conn, user_id)
    counts = conn.execute("""SELECT COALESCE(SUM(filter_reason IS NULL), 0) AS shown,
                                     COALESCE(SUM(filter_reason IS NOT NULL), 0) AS hidden
                              FROM user_jobs WHERE user_id = ?""", (user_id,)).fetchone()
    scored = conn.execute("SELECT COUNT(DISTINCT job_id) FROM scores WHERE user_id = ?", (user_id,)).fetchone()[0]
    top = conn.execute("""SELECT j.company, j.title,
                                 (SELECT s.score FROM scores s WHERE s.user_id = uj.user_id AND s.job_id = uj.job_id
                                  ORDER BY s.id DESC LIMIT 1) AS score
                          FROM user_jobs uj JOIN jobs j ON j.id = uj.job_id
                          WHERE uj.user_id = ? AND uj.filter_reason IS NULL
                          ORDER BY score IS NULL, score DESC, j.first_seen_at DESC LIMIT 20""", (user_id,)).fetchall()
    statuses = conn.execute("""SELECT status, COUNT(*) AS n FROM applications WHERE user_id = ?
                               GROUP BY status ORDER BY n DESC, status""", (user_id,)).fetchall()
    recent = conn.execute("""SELECT j.company, j.title, a.status, a.updated_at FROM applications a
                             JOIN jobs j ON j.id = a.job_id WHERE a.user_id = ?
                             ORDER BY a.updated_at DESC, a.id DESC LIMIT 20""", (user_id,)).fetchall()
    day, month = _periods(now)
    usage = conn.execute("""SELECT service, period, amount FROM usage WHERE user_id = ? AND period IN (?, ?)
                            ORDER BY service""", (user_id, day, month)).fetchall()
    up = get_user_prefs(conn, user_id)
    return {"account": dict(row), "onboarded": bool(onboarded_at), "prefs": up, "num": _num,
            "shown": counts["shown"], "hidden": counts["hidden"], "scored": scored, "top": top,
            "statuses": statuses, "recent": recent,
            "usage_today": [u for u in usage if u["period"] == day],
            "usage_month": [u for u in usage if u["period"] == month]}


@router.get("/users/{user_id}")
def user_view(user_id: int, request: Request, conn=Depends(get_conn)):
    view = user_overview(conn, user_id, datetime.now(UTC))
    if view is None:
        raise HTTPException(404)
    return render(request, conn, "admin_user.html", v=view)


@router.post("/invites")
def invite(request: Request, email: str = Form(...), conn=Depends(get_conn)):
    if "@" not in email:
        return _back(err="Enter an email address")
    email = email.strip().lower()
    add_invite(conn, email, request.state.user.id, datetime.now(UTC))
    return _back(msg=f"Invited {email}. Send them the link yourself", extra=f"&invited={quote(email)}")


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
