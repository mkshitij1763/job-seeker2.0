from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from jobseeker.db import queries
from jobseeker.web.deps import get_conn, render

router = APIRouter()


@router.get("/pipeline")
def pipeline(request: Request, conn=Depends(get_conn)):
    now = datetime.now(UTC)
    return render(request, conn, "pipeline.html", board=queries.pipeline(conn, now),
                  columns=queries.PIPELINE_COLUMNS, st=queries.stats(conn, now))
