from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import Depends, Request

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


def render(request: Request, conn, name: str, **ctx):
    run = last_run(conn, OWNER_ID)
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx.setdefault("err", request.query_params.get("err"))
    ctx["run_errors"] = json.loads(run["errors"]) if run else []
    ctx["run_notes"] = explain_run(ctx["run_errors"])
    ctx["run_finished"] = run["finished_at"] if run else None
    ctx["nav"] = nav_counts(conn, OWNER_ID)
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
