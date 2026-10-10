from fastapi import APIRouter, Depends, Request

from jobseeker.db import queries
from jobseeker.db.users import owner_first_name
from jobseeker.web.deps import get_conn, optional_user, render, render_public, require_onboarded

router = APIRouter()


@router.get("/")
def inbox(request: Request, band: str = "apply", family: str = "", city: str = "", source: str = "",
          status: str = "", user=Depends(optional_user), conn=Depends(get_conn)):
    if user is None:
        return render_public(request, conn, "landing.html", owner_first=owner_first_name(conn), invite_only=False)
    require_onboarded(user, conn)  # raises NotOnboarded → the user's onboarding step
    rows = queries.inbox(conn, user.id, band=band, family=family or None, city=city or None,
                         source=source or None, status=status or None)
    f = {"band": band, "family": family, "city": city, "source": source}
    show_pending = band in ("review", "all") or not rows
    pending = queries.pending_scores(conn, user.id) if show_pending else {"count": 0, "rows": []}
    return render(request, conn, "inbox.html", rows=rows, f=f, pending=pending, **queries.inbox_facets(conn, user.id))
