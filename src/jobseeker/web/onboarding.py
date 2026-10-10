from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from jobseeker.config import ITEM_MAX, LIST_MAX
from jobseeker.db import run_requests
from jobseeker.db.core import connect, iso
from jobseeker.db.profile import (claim_extract, extract_running, facts_row, get_facts, get_onboarding, get_user_prefs,
                                  load_user_context, save_facts, save_user_prefs, set_onboarding)
from jobseeker.pipeline.evaluate import reevaluate
from jobseeker.profile.extract import run_extract
from jobseeker.profile.facts import Achievement, Facts, Role
from jobseeker.profile.resume import MAX_BYTES, ResumeRejected, store_resume, validate_pdf
from jobseeker.web.deps import current_user, get_conn

router = APIRouter(prefix="/onboarding")
STEPS = ["roles", "where", "experience", "resume"]
MANUAL_ACHIEVEMENTS = 6
STILL_READING = "Still reading your previous upload; try again in a minute"
TITLE_DENY_MAX = 30
METRIC = re.compile(r"[\d][\d,.]*\s?(?:%|K\+?|M\+?|\+)?")


def _list(form, key) -> list[str]:
    vals = [v.strip() for v in form.getlist(key) if v.strip()]
    vals += [v.strip() for v in (form.get(f"{key}_text") or "").split(",") if v.strip()]
    return list(dict.fromkeys(vals))


def _num(raw, errors, key, lo, hi, msg):
    if raw in (None, ""):
        return None
    try:
        v = float(raw)
    except ValueError:
        errors[key] = msg
        return None
    if not lo <= v <= hi:
        errors[key] = msg
    return v


def parse_step(step: str, form, cfg) -> tuple[dict, dict[str, str]]:
    errors: dict[str, str] = {}
    if step == "roles":
        labels = {r.label for r in cfg.roles}
        roles = [r for r in form.getlist("roles") if r in labels]
        custom = (form.get("custom_role") or "").strip()
        if len(custom) > ITEM_MAX:
            errors["custom_role"] = f"Keep it under {ITEM_MAX} characters"
        if not roles and not custom:
            errors["roles"] = "Pick at least one role"
        fields = {"roles": roles, "custom_role": custom}
        if form.get("use_chips") == "1":  # Settings: drop custom matching, go back to the catalog's words
            fields.update(title_allow_extra=[], target_roles_text=[])
        elif "title_allow_extra_text" in form or "target_roles_text" in form:  # Settings' Advanced disclosure
            allow = [x.strip() for x in (form.get("title_allow_extra_text") or "").split(",") if x.strip()]
            prose = [x.strip() for x in (form.get("target_roles_text") or "").splitlines() if x.strip()]
            for key, items in (("title_allow_extra", allow), ("target_roles_text", prose)):
                if len(items) > TITLE_DENY_MAX or any(len(x) > ITEM_MAX for x in items):
                    errors[key] = f"Up to {TITLE_DENY_MAX} items of {ITEM_MAX} characters"
            fields.update(title_allow_extra=allow, target_roles_text=prose)
        return fields, errors
    if step == "where":
        cities = _list(form, "cities")
        remote = form.get("remote_india_ok") == "on"
        if not cities and not remote:
            errors["cities"] = "Pick a city or allow remote"
        if len(cities) > LIST_MAX:
            errors["cities"] = f"Up to {LIST_MAX} cities"
        return {"cities": cities, "remote_india_ok": remote, "where_confirmed": True}, errors
    if step == "experience":
        years = _num(form.get("experience_years"), errors, "experience_years", 0, 30, "Enter a number between 0 and 30")
        if years is None and "experience_years" not in errors:
            errors["experience_years"] = "Enter your years of experience"
        hide = _num(form.get("drop_if_min_years_at_least"), errors, "drop_if_min_years_at_least", 0, 40, "Enter a number")
        if hide is not None and years is not None and hide <= years:
            errors["drop_if_min_years_at_least"] = "Must be more than your years of experience"
        ctc = _num(form.get("current_ctc_lpa"), errors, "current_ctc_lpa", 0, 500, "Enter a number between 0 and 500")
        target = _num(form.get("target_base_lpa"), errors, "target_base_lpa", 0, 500, "Enter a number between 0 and 500")
        lists = {k: _list(form, k) for k in ("must_haves", "deal_breakers", "title_deny")}
        for k, v in lists.items():
            cap = TITLE_DENY_MAX if k == "title_deny" else LIST_MAX  # the default exclusions alone are 18 words
            if len(v) > cap or any(len(x) > ITEM_MAX for x in v):
                errors[k] = f"Up to {cap} items of {ITEM_MAX} characters"
        summary = (form.get("experience_summary") or "").strip()
        fields = {"experience_years": years, "drop_if_min_years_at_least": hide, "current_ctc_lpa": ctc,
                  "target_base_lpa": target, "experience_summary": summary, **lists}
        if not summary:
            fields.pop("experience_summary")  # drafted from the facts at the resume step if still empty
        return fields, errors
    raise HTTPException(404)


def _render(request, step, up, errors=None, status=200):
    cfg = request.app.state.app_config
    return request.app.state.templates.TemplateResponse(
        request, f"onboarding/{step}.html",
        {"up": up, "cfg": cfg, "errors": errors or {}, "step_no": STEPS.index(step) + 1, "steps": len(STEPS)},
        status_code=status)


# --- Resume and facts (shared with Settings, which passes base="/settings") ---------------------------------------

async def accept_upload(request: Request, conn, user_id: int, upload: UploadFile, background: BackgroundTasks) -> str:
    """Validate, store and (unless the same file was read before) queue fact extraction. Returns a flash message;
    raises ResumeRejected with the user-facing reason."""
    state, now = request.app.state, datetime.now(UTC)
    if extract_running(conn, user_id, now):  # storing now would let the running read save facts for the wrong file
        return STILL_READING
    data = await upload.read(MAX_BYTES + 1)  # never hold more than the limit
    validate_pdf(data, upload.content_type or "")
    _, sha = store_resume(state.settings.jobseeker_home, user_id, data)
    conn.execute("INSERT OR IGNORE INTO user_facts (user_id, updated_at) VALUES (?, ?)", (user_id, iso(now)))
    conn.execute("UPDATE user_facts SET resume_uploaded_at = ? WHERE user_id = ?", (iso(now), user_id))
    conn.commit()
    row = facts_row(conn, user_id)
    if row["resume_sha256"] == sha and row["facts"]:
        return "Resume saved. It's the same file as before, so your facts are unchanged."
    if claim_extract(conn, user_id, now):
        background.add_task(run_extract, state.settings.db_path, state.settings.jobseeker_home, user_id, sha,
                            state.app_config, state.llm_factory)
    if row["edited"] and row["facts"]:
        return "Your earlier edits were replaced by the new resume."
    return "Resume saved. Reading it now."


def status_context(conn, user_id: int, base: str) -> dict:
    return {"row": facts_row(conn, user_id) or {"extract_status": "idle", "extract_error": ""},
            "facts": get_facts(conn, user_id), "base": base, "manual_max": MANUAL_ACHIEVEMENTS}


def parse_facts_form(form, manual: bool = False) -> tuple[Facts | None, dict[str, str]]:
    errors: dict[str, str] = {}
    headline = (form.get("headline") or "").strip()
    skills = [x.strip() for x in (form.get("skills_text") or "").split(",") if x.strip()]
    orgs = form.getlist("achievement_org")
    pairs = [((orgs[i] if i < len(orgs) else "").strip(), t.strip())  # pair first, then drop the cleared ones
             for i, t in enumerate(form.getlist("achievement"))]
    pairs = [(o, t) for o, t in pairs if t]
    if manual:
        pairs = pairs[:MANUAL_ACHIEVEMENTS]
    roles = [Role(title=t.strip(), org=o.strip(), start=s.strip(), end=e.strip())
             for t, o, s, e in zip(form.getlist("role_title"), form.getlist("role_org"), form.getlist("role_start"),
                                   form.getlist("role_end")) if t.strip()]
    if not headline:
        errors["headline"] = "Add a one-line headline"
    if not skills:
        errors["skills"] = "Add at least one skill"
    if errors:
        return None, errors
    achievements = [Achievement(org=o, text=t, metrics=[m.strip() for m in METRIC.findall(t)]) for o, t in pairs]
    education = [x.strip() for x in form.getlist("education") if x.strip()]
    return Facts(headline=headline, roles=roles, achievements=achievements, skills=skills, education=education), {}


def save_facts_form(conn, user_id: int, form, manual: bool) -> dict[str, str]:
    facts, errors = parse_facts_form(form, manual)
    if errors:
        return errors
    now = datetime.now(UTC)
    row = facts_row(conn, user_id) or {}
    save_facts(conn, user_id, row.get("resume_sha256"), facts, edited=True, now=now)
    up = get_user_prefs(conn, user_id)
    summary = (form.get("experience_summary") or "").strip()
    if not summary and not up.experience_summary.strip():  # a plain-text draft from the facts, no LLM
        summary = "; ".join(f"{r.title} at {r.org} ({r.start}–{r.end})" for r in facts.roles) or facts.headline
    if summary:
        save_user_prefs(conn, user_id, up.model_copy(update={"experience_summary": summary}), now)
    return {}


def _already_onboarded(conn, user_id: int):
    """A finished user posting an onboarding form (stale tab, back button): change nothing, send them to Settings."""
    return RedirectResponse("/settings", 303) if get_onboarding(conn, user_id)[1] else None


def _resume_page(request, conn, user, errors=None, status=200, msg=None):
    ctx = {"up": get_user_prefs(conn, user.id), "step_no": 4, "steps": len(STEPS), "errors": errors or {},
           "msg": msg or request.query_params.get("msg"), "err": request.query_params.get("err"),
           **status_context(conn, user.id, "/onboarding")}
    return request.app.state.templates.TemplateResponse(request, "onboarding/resume.html", ctx, status_code=status)


@router.get("/resume")
def resume_page(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    if get_onboarding(conn, user.id)[1]:
        return RedirectResponse("/settings", 303)
    return _resume_page(request, conn, user)


@router.post("/resume")
async def resume_upload(request: Request, background: BackgroundTasks, resume: UploadFile = File(...),
                        user=Depends(current_user), conn=Depends(get_conn)):
    if done := _already_onboarded(conn, user.id):
        return done
    try:
        msg = await accept_upload(request, conn, user.id, resume, background)
    except ResumeRejected as e:
        return _resume_page(request, conn, user, {"resume": str(e)}, 422)
    return RedirectResponse(f"/onboarding/resume?msg={quote(msg)}", 303)


@router.get("/resume/status")
def resume_status(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    return request.app.state.templates.TemplateResponse(request, "_resume_status.html",
                                                        {"errors": {}, **status_context(conn, user.id, "/onboarding")})


@router.post("/facts")
async def facts_save(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    if done := _already_onboarded(conn, user.id):
        return done
    errors = save_facts_form(conn, user.id, await request.form(), manual=False)
    if errors:
        return _resume_page(request, conn, user, errors, 422)
    return RedirectResponse("/onboarding/resume?msg=Saved", 303)


@router.post("/facts/manual")
async def facts_manual(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    if done := _already_onboarded(conn, user.id):
        return done
    errors = save_facts_form(conn, user.id, await request.form(), manual=True)
    if errors:
        return _resume_page(request, conn, user, errors, 422)
    return RedirectResponse("/onboarding/resume?msg=Saved", 303)


def first_evaluation(db_path, user_id: int, app_config) -> None:
    """Background: the new user's first verdicts over every live job (no LLM, seconds)."""
    conn = connect(db_path)
    try:
        prefs, facts = load_user_context(conn, user_id, app_config)
        reevaluate(conn, user_id, prefs, facts, datetime.now(UTC), apply=True)
    finally:
        conn.close()


@router.post("/finish")
def finish(request: Request, background: BackgroundTasks, user=Depends(current_user), conn=Depends(get_conn)):
    if done := _already_onboarded(conn, user.id):
        return done
    missing = get_user_prefs(conn, user.id).complete()
    if missing:
        return RedirectResponse(f"/onboarding/{missing[0]}?err=Please+finish+this+step", 303)
    if get_facts(conn, user.id) is None:
        return RedirectResponse("/onboarding/resume?err=Add+your+resume+or+skills+first", 303)
    now = datetime.now(UTC)
    set_onboarding(conn, user.id, None, iso(now), now)
    try:  # their first scores: the next tick scores the top matches already in the DB (no fetch)
        run_requests.queue(conn, user.id, now, trigger="onboarding")
    except sqlite3.IntegrityError:  # already queued or running (a Fetch now from another tab): that run scores them
        conn.rollback()
    state = request.app.state
    background.add_task(first_evaluation, state.settings.db_path, user.id, state.app_config)
    return RedirectResponse("/onboarding/done", 303)


def _done_counts(conn, user_id: int) -> tuple[int, int]:
    row = conn.execute("SELECT COUNT(*), COALESCE(SUM(filter_reason IS NULL), 0) FROM user_jobs WHERE user_id = ?",
                       (user_id,)).fetchone()
    return row[0], row[1]


@router.get("/done")
def done(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    checked, matching = _done_counts(conn, user.id)
    return request.app.state.templates.TemplateResponse(request, "onboarding/done.html",
                                                        {"checked": checked, "matching": matching})


@router.get("/done/status")
def done_status(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    checked, matching = _done_counts(conn, user.id)
    return request.app.state.templates.TemplateResponse(request, "onboarding/_done_status.html",
                                                        {"checked": checked, "matching": matching})


@router.get("")
def start(user=Depends(current_user), conn=Depends(get_conn)):
    step, done = get_onboarding(conn, user.id)
    return RedirectResponse("/today" if done else f"/onboarding/{step or 'roles'}", 303)


@router.get("/{step}")
def show(request: Request, step: str, user=Depends(current_user), conn=Depends(get_conn)):
    if step not in STEPS[:3]:
        raise HTTPException(404)  # the resume step lives in Task 6's routes
    if get_onboarding(conn, user.id)[1]:
        return RedirectResponse("/", 303)
    return _render(request, step, get_user_prefs(conn, user.id))


@router.post("/{step}")
async def save(request: Request, step: str, user=Depends(current_user), conn=Depends(get_conn)):
    if step not in STEPS[:3]:
        raise HTTPException(404)
    if done := _already_onboarded(conn, user.id):
        return done
    form = await request.form()
    fields, errors = parse_step(step, form, request.app.state.app_config)
    up = get_user_prefs(conn, user.id).model_copy(update=fields)
    if errors:
        return _render(request, step, up, errors, 422)
    now = datetime.now(UTC)
    save_user_prefs(conn, user.id, up, now)
    nxt = STEPS[STEPS.index(step) + 1]
    set_onboarding(conn, user.id, nxt, None, now)
    return RedirectResponse(f"/onboarding/{nxt}", 303)
