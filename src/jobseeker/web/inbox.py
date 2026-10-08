from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from jobseeker.db import queries
from jobseeker.web.deps import get_conn, optional_user, render

router = APIRouter()


@router.get("/")
def inbox(request: Request, band: str = "apply", family: str = "", city: str = "", source: str = "",
          status: str = "", user=Depends(optional_user), conn=Depends(get_conn)):
    if user is None:  # sub-project 6 renders landing.html here
        return RedirectResponse("/login", 303)
    rows = queries.inbox(conn, user.id, band=band, family=family or None, city=city or None,
                         source=source or None, status=status or None)
    f = {"band": band, "family": family, "city": city, "source": source}
    return render(request, conn, "inbox.html", rows=rows, f=f, **queries.inbox_facets(conn, user.id))
