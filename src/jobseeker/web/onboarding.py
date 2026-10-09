from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from jobseeker.config import ITEM_MAX, LIST_MAX
from jobseeker.db.profile import get_onboarding, get_user_prefs, save_user_prefs, set_onboarding
from jobseeker.web.deps import current_user, get_conn

router = APIRouter(prefix="/onboarding")
STEPS = ["roles", "where", "experience", "resume"]


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
        return {"roles": roles, "custom_role": custom}, errors
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
            if len(v) > LIST_MAX or any(len(x) > ITEM_MAX for x in v):
                errors[k] = f"Up to {LIST_MAX} items of {ITEM_MAX} characters"
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
