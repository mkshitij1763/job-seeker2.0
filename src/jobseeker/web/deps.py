from __future__ import annotations

import json

from fastapi import Request

from jobseeker.db.core import connect
from jobseeker.db.runs import last_run


def get_conn(request: Request):
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def render(request: Request, conn, name: str, **ctx):
    run = last_run(conn)
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx.setdefault("err", request.query_params.get("err"))
    ctx["run_errors"] = json.loads(run["errors"]) if run else []
    return request.app.state.templates.TemplateResponse(request, name, ctx)
