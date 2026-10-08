from fastapi import APIRouter, Depends, Request

from jobseeker.db import queries
from jobseeker.db.users import OWNER_ID
from jobseeker.web.deps import get_conn, render

router = APIRouter()


@router.get("/")
def inbox(request: Request, band: str = "apply", family: str = "", city: str = "", source: str = "",
          status: str = "", conn=Depends(get_conn)):
    rows = queries.inbox(conn, OWNER_ID, band=band, family=family or None, city=city or None,
                         source=source or None, status=status or None)
    f = {"band": band, "family": family, "city": city, "source": source}
    return render(request, conn, "inbox.html", rows=rows, f=f, **queries.inbox_facets(conn, OWNER_ID))
