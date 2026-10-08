from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request

from jobseeker.db.core import connect
from jobseeker.db.runs import last_run
from jobseeker.db.sessions import user_for_token
from jobseeker.db.users import OWNER_ID, User
from jobseeker.web.filters import explain_run
from jobseeker.web.oauth import SESSION_COOKIE
from jobseeker.web.view import nav_counts


def get_conn(request: Request):
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def render_public(request: Request, conn, name: str, status_code: int = 200, **ctx):
    """render() for signed-out pages: no nav counts or run notes, because there's no user."""
    ctx.setdefault("msg", request.query_params.get("msg"))
    return request.app.state.templates.TemplateResponse(request, name, ctx, status_code=status_code)


def render(request: Request, conn, name: str, **ctx):
    user = request.state.user  # set by optional_user/current_user on every guarded route
    run = last_run(conn, user.id)
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx.setdefault("err", request.query_params.get("err"))
    ctx["run_errors"] = json.loads(run["errors"]) if run else []
    ctx["run_notes"] = explain_run(ctx["run_errors"])
    ctx["run_finished"] = run["finished_at"] if run else None
    ctx["nav"] = nav_counts(conn, user.id)
    ctx["user"] = user
    return request.app.state.templates.TemplateResponse(request, name, ctx)


class NotAuthenticated(Exception):
    pass


def optional_user(request: Request, conn=Depends(get_conn)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    found = user_for_token(conn, token, datetime.now(UTC)) if token else None
    if not found:
        return None
    user, refreshed = found
    if refreshed:
        request.state.refresh_session = token
    request.state.user = user
    return user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise NotAuthenticated()
    return user


def owned_app(app_id: int, user: User = Depends(current_user), conn=Depends(get_conn)) -> int:
    if not conn.execute("SELECT 1 FROM applications WHERE id = ? AND user_id = ?", (app_id, user.id)).fetchone():
        raise HTTPException(404)  # 404, not 403: never confirm another user's ids exist
    return app_id


def current_prefs(request: Request, user: User = Depends(current_user), conn=Depends(get_conn)):
    """The signed-in user's effective Preferences, read fresh per request (cached within it by FastAPI)."""
    from jobseeker.db.profile import load_user_context
    return load_user_context(conn, user.id, request.app.state.app_config)[0]


def current_facts(user: User = Depends(current_user), conn=Depends(get_conn)):
    from jobseeker.db.profile import get_facts
    return get_facts(conn, user.id)


def require_owner(user: User = Depends(current_user)) -> User:
    """Interim outreach gate: contacts and company domains are shared rows, so only the owner may write them until
    sub-project 5 makes contacts per user (it replaces this with require_outreach)."""
    if user.id != OWNER_ID:
        raise HTTPException(404)
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(404)
    return user
