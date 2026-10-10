from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from jobseeker.clock import app_now
from jobseeker.db import queries
from jobseeker.web.deps import current_user, get_conn, render

router = APIRouter()


@router.get("/pipeline")
def pipeline(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    now = datetime.now(UTC)
    return render(request, conn, "pipeline.html", board=queries.pipeline(conn, user.id, now),
                  columns=queries.PIPELINE_COLUMNS, st=queries.stats(conn, user.id, now))


def _local_hour() -> int:
    return app_now().hour


@router.get("/today")
def today(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    first_run = not queries.has_any_score(conn, user.id)  # a new user: "All caught up" would be untrue
    return render(request, conn, "today.html", t=queries.today(conn, user.id, datetime.now(UTC)), now_hour=_local_hour(),
                  first_run=first_run, pending=queries.pending_scores(conn, user.id, 0)["count"] if first_run else 0)
