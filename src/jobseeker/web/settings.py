from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response

from jobseeker.config import effective_prefs
from jobseeker.db.account import delete_account, export_zip
from jobseeker.db.profile import facts_row, get_user_prefs, load_user_context, save_user_prefs
from jobseeker.db.users import LastAdmin
from jobseeker.pipeline.evaluate import reevaluate
from jobseeker.profile.resume import ResumeRejected
from jobseeker.web.deps import current_user, get_conn, render
from jobseeker.web.oauth import SESSION_COOKIE
from jobseeker.web.onboarding import accept_upload, parse_step, save_facts_form, status_context

router = APIRouter(prefix="/settings")
FILTER_FIELDS = {"roles", "custom_role", "cities", "remote_india_ok", "drop_if_min_years_at_least", "title_deny",
                 "title_allow_extra"}
SECTIONS = {"roles", "where", "experience"}


def _back(msg="", err=""):
    q = f"?msg={quote(msg)}" if msg else (f"?err={quote(err)}" if err else "")
    return RedirectResponse(f"/settings{q}", 303)


def _page(request, conn, user, status: int = 200, **ctx):
    ctx.setdefault("up", get_user_prefs(conn, user.id))
    ctx.setdefault("errors", {})
    ctx.setdefault("vapid_public_key", request.app.state.settings.vapid_public_key)
    response = render(request, conn, "settings.html", cfg=request.app.state.app_config,
                      facts_info=facts_row(conn, user.id), **status_context(conn, user.id, "/settings"), **ctx)
    response.status_code = status
    return response


@router.get("")
def page(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    return _page(request, conn, user)


@router.post("/profile")
def profile(linkedin: str = Form(""), github: str = Form(""), user=Depends(current_user), conn=Depends(get_conn)):
    links = {"linkedin": linkedin.strip(), "github": github.strip()}
    if any(v and not v.startswith("https://") for v in links.values()):
        return _back(err="Links must start with https://")
    save_user_prefs(conn, user.id, get_user_prefs(conn, user.id).model_copy(update=links), datetime.now(UTC))
    return _back(msg="Profile saved")


@router.post("/prefs/alerts")  # declared before /prefs/{section}, which would otherwise catch it
def save_alerts(notify_new_matches: str | None = Form(None), user=Depends(current_user), conn=Depends(get_conn)):
    up = get_user_prefs(conn, user.id).model_copy(update={"notify_new_matches": bool(notify_new_matches)})
    save_user_prefs(conn, user.id, up, datetime.now(UTC))
    return RedirectResponse("/settings?msg=Saved#alerts", 303)


@router.post("/prefs/{section}")
async def save_prefs(request: Request, section: str, user=Depends(current_user), conn=Depends(get_conn)):
    if section not in SECTIONS:
        return _back(err="Unknown section")
    form = await request.form()
    cfg = request.app.state.app_config
    fields, errors = parse_step(section, form, cfg)
    old = get_user_prefs(conn, user.id)
    new = old.model_copy(update=fields)
    if errors:
        return _page(request, conn, user, 422, up=new, errors=errors, open_section=section)
    now = datetime.now(UTC)
    if not any(getattr(old, f) != getattr(new, f) for f in FILTER_FIELDS):
        save_user_prefs(conn, user.id, new, now)
        return _back(msg="Saved. Scores refresh over the next runs")
    prefs, facts = load_user_context(conn, user.id, cfg)
    candidate = effective_prefs(new, cfg, prefs.name, prefs.email)
    if form.get("confirm") != "1":
        report = await run_in_threadpool(reevaluate, conn, user.id, candidate, facts, now, False)
        return _page(request, conn, user, up=new, open_section=section, preview=report,
                     preview_form=[(k, v) for k, v in form.multi_items() if k != "confirm"])
    save_user_prefs(conn, user.id, new, now)
    report = await run_in_threadpool(reevaluate, conn, user.id, candidate, facts, now, True)
    return _back(msg=f"Saved: {len(report.hidden)} hidden, {len(report.restored)} back, "
                     f"{len(report.skipped_apps)} skipped (Undo works on each)")


@router.post("/resume")
async def resume(request: Request, background: BackgroundTasks, resume: UploadFile = File(...),
                 user=Depends(current_user), conn=Depends(get_conn)):
    try:
        msg = await accept_upload(request, conn, user.id, resume, background)
    except ResumeRejected as e:
        return _page(request, conn, user, 422, errors={"resume": str(e)}, open_section="resume")
    return _back(msg=msg)


@router.get("/resume/status")
def resume_status(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    return request.app.state.templates.TemplateResponse(
        request, "_resume_status.html", {"errors": {}, "up": get_user_prefs(conn, user.id),
                                         **status_context(conn, user.id, "/settings")})


@router.post("/facts")
async def facts(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    errors = save_facts_form(conn, user.id, await request.form(), manual=False)
    if errors:
        return _page(request, conn, user, 422, errors=errors, open_section="resume")
    return _back(msg="Facts saved")


@router.post("/facts/manual")
async def facts_manual(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    errors = save_facts_form(conn, user.id, await request.form(), manual=True)
    if errors:
        return _page(request, conn, user, 422, errors=errors, open_section="resume")
    return _back(msg="Facts saved")


# Export and delete: signed in, but not require_onboarded, so a user can always take their data or leave.
account_router = APIRouter(prefix="/settings")


def _only_admin(conn, user) -> bool:
    return bool(user.is_admin) and not conn.execute(
        "SELECT 1 FROM users WHERE is_admin = 1 AND disabled_at IS NULL AND id != ?", (user.id,)).fetchone()


@account_router.get("/export")
def export(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    data = export_zip(conn, request.app.state.settings.jobseeker_home, user.id)
    name = f"jobseeker-{user.email}-{datetime.now(UTC):%Y-%m-%d}.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _delete_page(request, conn, user, status=200, error=""):
    return request.app.state.templates.TemplateResponse(
        request, "settings_delete.html", {"user": user, "only_admin": _only_admin(conn, user), "error": error},
        status_code=status)


@account_router.get("/delete")
def delete_page(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    return _delete_page(request, conn, user)


@account_router.post("/delete")
def delete(request: Request, email: str = Form(""), user=Depends(current_user), conn=Depends(get_conn)):
    if email.strip().lower() != user.email.lower():
        return _delete_page(request, conn, user, 422, "The email doesn't match")
    try:
        delete_account(conn, request.app.state.settings.jobseeker_home, user.id)
    except LastAdmin:
        return _delete_page(request, conn, user, 403, "You're the only admin")
    s = request.app.state.settings
    resp = RedirectResponse("/login", 303)
    resp.delete_cookie(SESSION_COOKIE, path="/", secure=s.cookie_secure, httponly=True, samesite="lax")
    return resp
