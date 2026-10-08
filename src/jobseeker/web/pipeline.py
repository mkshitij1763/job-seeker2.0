from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from jobseeker.db import queries
from jobseeker.db.users import OWNER_ID
from jobseeker.web.deps import get_conn, render

router = APIRouter()


@router.get("/pipeline")
def pipeline(request: Request, conn=Depends(get_conn)):
    now = datetime.now(UTC)
    return render(request, conn, "pipeline.html", board=queries.pipeline(conn, OWNER_ID, now),
                  columns=queries.PIPELINE_COLUMNS, st=queries.stats(conn, OWNER_ID, now))


def _local_hour() -> int:
    return datetime.now().astimezone().hour


@router.get("/today")
def today(request: Request, conn=Depends(get_conn)):
    return render(request, conn, "today.html", t=queries.today(conn, OWNER_ID, datetime.now(UTC)), now_hour=_local_hour())
