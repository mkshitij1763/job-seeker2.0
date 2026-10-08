from __future__ import annotations

import json

from fastapi import Request

from jobseeker.db.core import connect
from jobseeker.db.runs import last_run
from jobseeker.db.users import OWNER_ID
from jobseeker.web.filters import explain_run
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
