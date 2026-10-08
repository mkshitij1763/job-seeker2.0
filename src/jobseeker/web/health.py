"""GET/HEAD /healthz for the uptime monitor: a read-only DB check that never migrates or writes."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from jobseeker.db.migrations import latest

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}


def check(db_path: Path) -> tuple[int, dict]:
    path = Path(db_path)
    if not path.is_file():
        return 503, {"ok": False, "check": "db"}
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2.0)
        try:
            conn.execute("SELECT 1")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 503, {"ok": False, "check": "db"}
    if version != latest():
        return 503, {"ok": False, "check": "schema"}
    return 200, {"ok": True}


@router.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
def healthz(request: Request):
    status, body = check(request.app.state.settings.db_path)
    if request.method == "HEAD":
        return Response(status_code=status, headers=NO_STORE)
    return JSONResponse(body, status_code=status, headers=NO_STORE)
