from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from jobseeker.db import queries
from jobseeker.web.deps import current_user, get_conn, render

router = APIRouter()


@router.get("/pipeline")
def pipeline(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    now = datetime.now(UTC)
    return render(request, conn, "pipeline.html", board=queries.pipeline(conn, user.id, now),
                  columns=queries.PIPELINE_COLUMNS, st=queries.stats(conn, user.id, now))


def _local_hour() -> int:
    return datetime.now().astimezone().hour


@router.get("/today")
def today(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    return render(request, conn, "today.html", t=queries.today(conn, user.id, datetime.now(UTC)), now_hour=_local_hour())
